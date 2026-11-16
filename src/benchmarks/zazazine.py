"""
ZAZAZINE (zazazine.verdindex.com) benchmark pages.

Representative crawled pages of ZAZAZINE (zazazine.verdindex.com). One benchmark site among others:
its roles, clusters and thresholds live in config/sites/zazazine.yaml, exactly like
any user's site config; nothing in the engines is specific to it.
"""

from typing import List

from src.connectors.sitemap_crawler import ParsedPage


def build_zazazine_pages() -> List[ParsedPage]:
    return [
        # --- CLUSTER 1: CANNABIS & POLÍTICA REGULATÓRIA ---
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/cure-act-projeto-protege-usuarios-de-maconha-em-empregos-federais",
            title="CURE Act: projeto protege usuários de maconha em empregos federais",
            h1="CURE Act: projeto protege usuários de maconha em empregos federais",
            paragraphs=[
                "Os deputados Jamin Raskin e Zachary Nunn apresentaram o CURE Act, que visa proteger candidatos a empregos federais nos EUA que usaram maconha no passado.",
                "O CURE Act estabelece que, dentro de um ano após a aprovação, as agências teriam que revisar todas as negações anteriores desde 1º de janeiro de 2008.",
                "O CURE Act se conecta à discussão mais ampla de reclassificação federal da cannabis para a Schedule III e ao estigma que o uso passado ainda carrega mesmo em estados regulamentados.",
                "Para quem busca informações sobre cultivo medicinal e acesso legal no Brasil, o ecossistema apoia pacientes por meio de associações canábicas de cultivo.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/dea-deixa-estados-no-escuro-sobre-reclassificacao-da-cannabis",
            title="DEA deixa estados no escuro sobre reclassificação da cannabis",
            h1="DEA deixa estados no escuro sobre reclassificação da cannabis",
            paragraphs=[
                "A DEA (Drug Enforcement Administration) está sendo acusada de não demonstrar interesse em ajudar os estados a se prepararem para a reclassificação da maconha, segundo Clint Kellum, regulador da Califórnia.",
                "Segundo apuração, o processo federal de rescheduling para a Schedule III está estagnado e pouco transparente para os reguladores estaduais.",
                "Enquanto a reclassificação federal não avança com diretrizes claras, estados como a Califórnia e Virgínia ajustam suas próprias legislações de varejo para adultos.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/dc-circuit-rejeita-bloquear-reclassificacao-maconha",
            title="Tribunal federal deixa a reclassificação da maconha para a Schedule III seguir",
            h1="Tribunal federal deixa a reclassificação da maconha para a Schedule III seguir",
            paragraphs=[
                "O Tribunal de Apelações do Circuito de DC rejeitou o pedido de grupos proibicionistas para suspender o processo de reclassificação da maconha promovido pelo DOJ e DEA.",
                "A decisão mantém o cronograma de audiências públicas administrativas para consolidar a transferência da cannabis da Schedule I para a Schedule III.",
                "Isso complementa iniciativas legislativas no Congresso americano, incluindo projetos bipartidários como o CURE Act que tratam dos direitos civis de usuários.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/virginia-varejo-cannabis-hb-30",
            title="Virgínia legaliza a venda de cannabis e adultos 21+ já podem consumir e cultivar",
            h1="Virgínia legaliza a venda de cannabis no varejo",
            paragraphs=[
                "A Virgínia consolidou seu modelo de licenciamento de dispensários e varejo legal para adultos acima de 21 anos com o projeto HB 30.",
                "Além da compra comercial em dispensários licenciados, os residentes do estado mantêm o direito ao autocultivo de até quatro plantas por domicílio.",
                "Pacientes e entusiastas buscam mapear os perfis de canabinoides e terpenos específicos através de catálogos detalhados de strains.",
            ],
            existing_internal_links=[],
        ),

        # --- CLUSTER 2: TECNOLOGIA & IA ---
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/custo-de-ia-cai-47-por-trimestre",
            title="Custo de IA cai 47% por trimestre",
            h1="Custo de IA cai 47% por trimestre",
            paragraphs=[
                "Pesquisa da Epoch AI mostra que o custo de desempenho de modelos de IA caiu 47% por trimestre desde 2023, tornando a inferência de fronteira acessível.",
                "Um exemplo concreto dessa curva de custo caindo é a nova geração de modelos de texto-para-voz do Google Gemini 3.8 com clonagem de voz ultra-barata.",
                "A indústria criativa e as grandes gravadoras agora aproveitam essa redução acelerada para investir em infraestrutura com ElevenLabs e Stability AI.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/google-lanca-gemini-3-8",
            title="Google lança Gemini 3.8",
            h1="Google lança modelos de texto-para-voz Gemini 3.8",
            paragraphs=[
                "Google lança modelos de texto-para-voz Gemini 3.8 com suporte a mais de 2.000 vozes e 100 idiomas com custos reduzidos em mais de 70%.",
                "Os modelos Flash e Flash-Lite oferecem clonagem de voz de alta fidelidade com marca d'água SynthID para proteção de propriedade intelectual.",
                "O lançamento reforça como o custo de modelos de IA de última geração vem caindo a cada trimestre na disputa com a Anthropic e OpenAI.",
            ],
            existing_internal_links=[],
        ),
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/majors-stability-ai-universal-elevenlabs",
            title="Majors investem na Stability AI e Universal fecha parceria com a ElevenLabs",
            h1="Universal, Sony e Warner investem na Stability AI",
            paragraphs=[
                "Universal, Sony e Warner participam de rodada Series B de US$ 76 milhões na Stability AI, ao mesmo tempo em que a Universal fecha aliança com a ElevenLabs.",
                "As gravadoras buscam regulamentar o uso de vozes e stems protegidos por direitos autorais em plataformas comerciais de inteligência artificial.",
                "A estratégia responde à rápida queda no custo de computação e inferência de IA que popularizou clones vocais de artistas globais na internet.",
            ],
            existing_internal_links=[],
        ),

        # --- CLUSTER 3: MÚSICA & STREETWEAR (Cultura de Rua) ---
        ParsedPage(
            url="https://zazazine.verdindex.com/artigo/streetwear-2026-oversize-arquitetonico-eco-utility",
            title="Streetwear 2026: menos logo, mais caimento, oversize arquitetônico e eco-utility",
            h1="O Streetwear em 2026: Caimento Arquitetônico e Utility",
            paragraphs=[
                "O streetwear em 2026 abandona a logomania exagerada em favor de modelagens volumosas, alfaiataria desconstruída e materiais eco-friendly.",
                "Artistas independentes da cena musical de Londres e São Paulo são as principais referências visuais dessa nova fase do vestuário de rua.",
                "Colaborações icônicas de calçados vintage voltam aos holofotes com lançamentos comemorativos e parcerias da moda urbana global.",
            ],
            existing_internal_links=[],
        ),
    ]
