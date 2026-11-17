"""
SEO-Magus evaluation command line (see docs/EVALUATION.md).

  python -m src.evaluation synthetic      --pages 2000 --preset encyclopedia --out C.jsonl.gz
  python -m src.evaluation wikipedia      --contact you@example.com --categories Composting Astronomy --out C.jsonl.gz
  python -m src.evaluation archive        --contact you@example.com --collections gutenberg prelinger --out C.jsonl.gz
  python -m src.evaluation stackexchange  --dump DIR --site gardening.stackexchange.com --out C.jsonl.gz
  python -m src.evaluation crawl          --url https://your-site.example/ --out C.jsonl.gz   (or --from-crawl FILE)
  python -m src.evaluation clickstream    --corpus C.jsonl.gz --tsv clickstream-enwiki-2024-01.tsv.gz
  python -m src.evaluation run            C1.jsonl.gz C2.jsonl.gz ... --out build/eval
  python -m src.evaluation crawl-fidelity C.jsonl.gz --out build/eval-crawl
  python -m src.evaluation scale          --sizes 1000 3000 10000 --out build/eval-scale
  python -m src.evaluation info           C.jsonl.gz
  python -m src.evaluation export         build/eval/report.json --out build/eval --level simple
  python -m src.evaluation compare        build/eval-old/report.json build/eval/report.json --out build/eval-compare
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from src.evaluation.corpus import Corpus
from src.evaluation.protocol import PROTOCOL
from src.log import configure_logging, get_logger, run_context

logger = get_logger("src.evaluation.cli")       # __name__ is "__main__" under `python -m`

DEFAULT_CACHE = "build/eval/cache"


def _client(args):
    from src.evaluation.sources.http import HttpJsonClient
    agent = f"SEO-Magus-evaluation/1.0 ({args.contact})" if args.contact else "SEO-Magus-evaluation/1.0"
    return HttpJsonClient(agent, cache_dir=args.cache, min_interval=args.interval, offline=args.offline)


def _saved(corpus: Corpus, out: str) -> None:
    path = corpus.save(out)
    print(f"{corpus.name}: {len(corpus)} documents, layers {sorted(corpus.layers)}, fingerprint {corpus.fingerprint()} "
          f"-> {path}")


def cmd_synthetic(args):
    from src.evaluation.sources.synthetic import SyntheticSpec, generate
    _saved(generate(SyntheticSpec(pages=args.pages, topics=args.topics, seed=args.seed, preset=args.preset,
                                  language=args.language)), args.out)


def cmd_wikipedia(args):
    from src.evaluation.sources.wikipedia import WikipediaSource
    source = WikipediaSource(_client(args), args.lang)
    corpus = source.build(args.name or f"wikipedia-{args.lang}", seeds=args.seeds or (), categories=args.categories or (),
                          random_count=args.random or 0, limit=args.limit, seed=args.seed)
    _saved(corpus, args.out)


def cmd_archive(args):
    from src.evaluation.sources.internet_archive import InternetArchiveSource
    corpus = InternetArchiveSource(_client(args)).build(args.name or "internet-archive", args.collections,
                                                        limit=args.limit, seed=args.seed, mediatype=args.mediatype)
    _saved(corpus, args.out)


def cmd_stackexchange(args):
    from src.evaluation.sources.stackexchange import StackExchangeDump
    dump = StackExchangeDump(args.dump, args.site)
    _saved(dump.import_dump(args.name or f"stackexchange-{dump.host}", limit=args.limit, seed=args.seed,
                            tags=args.tags or ()), args.out)


def cmd_crawl(args):
    from src.evaluation.sources.site_crawl import crawl_site, from_crawl
    if args.from_crawl:
        from src.connectors.sitemap_crawler import CrawlResult
        corpus = from_crawl(CrawlResult.load(args.from_crawl), args.name or Path(args.from_crawl).stem)
    else:
        corpus = crawl_site(args.url, args.name or "crawled-site", max_pages=args.max_pages)
    _saved(corpus, args.out)


def cmd_clickstream(args):
    from src.evaluation.sources.wikipedia import load_clickstream, open_clickstream
    corpus = load_clickstream(Corpus.load(args.corpus), open_clickstream(args.tsv), args.lang)
    _saved(corpus, args.out or args.corpus)


def cmd_run(args):
    from src.evaluation.report import write_report
    from src.evaluation.runner import evaluate
    from src.evaluation.systems import link_systems
    classifier = None
    if args.config:
        from src.config import load_site_config
        from src.engines.classifiers import build_classifier
        settings = load_site_config(args.config).classifier
        classifier = lambda: build_classifier(settings)
        print(f"SEO-Magus systems use the classifier of {args.config}: {build_classifier(settings).describe()}")
    corpora = [Corpus.load(path) for path in args.corpora]
    systems = [s for s in link_systems(classifier) if not args.systems or s.name in args.systems]
    report = evaluate(corpora, args.tasks, args.samplers, args.seeds, args.sample_size, args.protocols, systems,
                      progress=lambda message: print(f"  {message}", flush=True))
    for path in write_report(report, args.out, level=args.export):
        print(f"report: {path}")


def cmd_export(args):
    from src.evaluation.report import write_report
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    for path in write_report(report, args.out or Path(args.report).parent, level=args.level, label=args.label):
        print(f"export: {path}")


def cmd_compare(args):
    from src.evaluation.compare import compare_reports, write_comparison
    from src.evaluation.results import load_rows
    labels = args.labels or [Path(p).parent.name if Path(p).suffix == ".json" else Path(p).stem for p in args.reports]
    if len(labels) != len(args.reports):
        raise SystemExit("--labels needs one label per report")
    if len(set(labels)) != len(labels):
        labels = [f"{label}#{i + 1}" for i, label in enumerate(labels)]
    result = compare_reports({label: load_rows(path, label) for label, path in zip(labels, args.reports)})
    for c in result["comparisons"]:
        print(f"{c['reference']} -> {c['other']}: {c['mode']}" + (f" ({'; '.join(c['reasons'])})" if c["reasons"] else ""))
    for path in write_comparison(result, args.out):
        print(f"comparison: {path}")


def cmd_crawl_fidelity(args):
    from src.evaluation.crawl_eval import crawl_fidelity
    results = []
    for path in args.corpora:
        corpus = Corpus.load(path)
        result = {"corpus": corpus.name, **crawl_fidelity(corpus, concurrency=args.concurrency)}
        print(json.dumps(result))
        results.append(result)
    _merge(args.out, "crawl", results)


def cmd_scale(args):
    from src.evaluation.scale import scale_task
    result = scale_task(args.sizes, preset=args.preset, seed=args.seed, brute_max=args.exhaustive_max,
                        progress=lambda message: print(f"  {message}", flush=True))
    print(f"time ~ n^{result['time_exponent']:.2f}, classifier calls ~ n^{result['calls_exponent']:.2f}")
    _merge(args.out, "scale", result)


def _merge(out: str, key: str, value) -> None:
    """Add crawl / scale results to an existing report (or start one) and re-render it."""
    from src.evaluation.report import write_report
    path = Path(out) / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"protocol": PROTOCOL}
    report[key] = value
    for written in write_report(report, out):
        print(f"report: {written}")


def cmd_info(args):
    for path in args.corpora:
        corpus = Corpus.load(path)
        links = sum(len(d.links) for d in corpus.documents)
        labels = {d.labels[0] for d in corpus.documents if d.labels}
        print(f"{path}: {corpus.name} | {len(corpus)} documents | {links} in-prose links | {len(labels)} primary labels "
              f"| layers {sorted(corpus.layers)} | fingerprint {corpus.fingerprint()}")
        print(f"  provenance: {json.dumps(vars(corpus.provenance), ensure_ascii=False)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.evaluation", description="SEO-Magus evaluation")
    parser.add_argument("-v", "--verbose", action="store_true", help="log progress (INFO)")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING (default) or ERROR; env SEO_MAGUS_LOG_LEVEL")
    parser.add_argument("--log-file", default=None, help="also write the logs to this file")
    sub = parser.add_subparsers(dest="command", required=True)

    def live(p):
        p.add_argument("--contact", default=None, help="e-mail or URL sent in the User-Agent (required when fetching)")
        p.add_argument("--cache", default=DEFAULT_CACHE, help="record/replay cache directory")
        p.add_argument("--offline", action="store_true", help="replay the cache only, never touch the network")
        p.add_argument("--interval", type=float, default=0.5, help="minimum seconds between requests")

    def common(p, out_required=True):
        p.add_argument("--out", required=out_required, help="corpus file to write (.jsonl.gz)")
        p.add_argument("--name", default=None, help="corpus name")
        p.add_argument("--limit", type=int, default=500, help="maximum documents")
        p.add_argument("--seed", type=int, default=0)

    p = sub.add_parser("synthetic", help="generate a synthetic corpus (ground truth by construction)")
    p.add_argument("--pages", type=int, default=1000)
    p.add_argument("--topics", type=int, default=12)
    p.add_argument("--preset", choices=["encyclopedia", "catalog", "forum"], default="encyclopedia")
    p.add_argument("--language", choices=["en", "pt"], default="en")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_synthetic)

    p = sub.add_parser("wikipedia", help="sample Wikipedia through the MediaWiki API")
    common(p)
    live(p)
    p.add_argument("--lang", default="en", help="language edition (en, pt, ...)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--seeds", nargs="+", help="snowball from these articles")
    group.add_argument("--categories", nargs="+", help="equal shares of these categories' members")
    group.add_argument("--random", type=int, help="this many random articles")
    p.set_defaults(func=cmd_wikipedia)

    p = sub.add_parser("archive", help="sample Internet Archive collections (advancedsearch API)")
    common(p)
    live(p)
    p.add_argument("--collections", nargs="+", required=True)
    p.add_argument("--mediatype", default=None, help="e.g. texts, movies, audio")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("stackexchange", help="import a Stack Exchange data dump (Posts.xml, PostLinks.xml)")
    common(p)
    p.add_argument("--dump", required=True, help="directory with the extracted dump")
    p.add_argument("--site", required=True, help="site host, e.g. gardening.stackexchange.com")
    p.add_argument("--tags", nargs="+", default=None, help="equal shares of these tags (default: random)")
    p.set_defaults(func=cmd_stackexchange)

    p = sub.add_parser("crawl", help="crawl a website (or convert a saved crawl) into a corpus")
    common(p)
    p.add_argument("--url", default=None)
    p.add_argument("--from-crawl", default=None, help="a crawl saved with `crawl --save-crawl`")
    p.add_argument("--max-pages", type=int, default=500)
    p.set_defaults(func=cmd_crawl)

    p = sub.add_parser("clickstream", help="attach a Wikipedia clickstream dump to a Wikipedia corpus")
    p.add_argument("--corpus", required=True)
    p.add_argument("--tsv", required=True, help="clickstream-<wiki>-<month>.tsv(.gz)")
    p.add_argument("--lang", default="en")
    p.add_argument("--out", default=None, help="default: overwrite --corpus")
    p.set_defaults(func=cmd_clickstream)

    p = sub.add_parser("run", help="run the protocol on corpora and write the report")
    p.add_argument("corpora", nargs="+")
    p.add_argument("--out", default="build/eval")
    p.add_argument("--tasks", nargs="+", default=["links", "classification", "ranking"],
                   choices=["links", "classification", "ranking"])
    p.add_argument("--samplers", nargs="+", default=None, choices=PROTOCOL["samplers"])
    p.add_argument("--seeds", nargs="+", type=int, default=None)
    p.add_argument("--sample-size", type=int, default=None)
    p.add_argument("--protocols", nargs="+", default=None, choices=list(PROTOCOL["link_protocols"]))
    p.add_argument("--systems", nargs="+", default=None, help="link systems to run (default: all)")
    p.add_argument("--config", default=None,
                   help="site config whose classifier the SEO-Magus systems use (default: offline heuristic)")
    p.add_argument("--export", choices=["simple", "full"], default="full",
                   help="simple: report.md, summary.csv, claims.csv; full: also tidy rows, analysis.json, report.html")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("export", help="re-write the exports of a report.json (e.g. after an update of the report code)")
    p.add_argument("report", help="a report.json written by `run`")
    p.add_argument("--out", default=None, help="directory (default: the report's directory)")
    p.add_argument("--level", choices=["simple", "full"], default="full")
    p.add_argument("--label", default=None, help="name of this report in the tidy rows (default: its directory name)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("compare", help="compare reports (code versions, protocols, settings); the first is the reference")
    p.add_argument("reports", nargs="+", help="report.json, results.jsonl or runs.csv files")
    p.add_argument("--labels", nargs="+", default=None, help="a name per report (default: directory names)")
    p.add_argument("--out", default="build/eval-compare")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("crawl-fidelity", help="render corpora as sites, crawl them over HTTP, compare")
    p.add_argument("corpora", nargs="+")
    p.add_argument("--out", default="build/eval")
    p.add_argument("--concurrency", type=int, default=8)
    p.set_defaults(func=cmd_crawl_fidelity)

    p = sub.add_parser("scale", help="time and classifier calls against site size")
    p.add_argument("--sizes", nargs="+", type=int, default=[300, 1000, 3000, 10000])
    p.add_argument("--preset", choices=["encyclopedia", "catalog", "forum"], default="encyclopedia")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--exhaustive-max", type=int, default=300, help="also run the exhaustive flow up to this size")
    p.add_argument("--out", default="build/eval")
    p.set_defaults(func=cmd_scale)

    p = sub.add_parser("info", help="describe corpus files")
    p.add_argument("corpora", nargs="+")
    p.set_defaults(func=cmd_info)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level or ("INFO" if args.verbose else None), args.log_file)
    logger.info("Evaluation command: %s%s", args.command, run_context())
    from urllib.error import URLError
    from src.evaluation.sources.http import OfflineCacheMiss
    try:
        args.func(args)
    except OfflineCacheMiss as exc:
        logger.error("%s - run once with network access to record it", exc)
        return 2
    except URLError as exc:
        logger.error("Network error: %s. Live sources need network access; with a recorded cache use --offline.",
                     getattr(exc, "reason", exc))
        return 2
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
