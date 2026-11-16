# TypeSafe Jev Integration Guide

This guide details how **TypeSafe Jev** (System One) is integrated into `SEO-magus` for lightning-fast, ultra-low cost decision making, alongside auxiliary LLMs (System Two).

> **Jev is the default link classifier, not a requirement.** The optimizer talks to the provider-agnostic
> `LinkClassifier` interface (`src/engines/classifiers/`). With `classifier.provider: auto` (the default) Jev is used
> whenever `TYPESAFE_API_KEY` is set; any OpenAI-compatible, Anthropic, local (Ollama, LM Studio) or custom Python
> classifier can be configured instead – see the README section "Choosing the link classifier".

---

## 1. TypeSafe Jev Overview

* **Endpoint:** `POST https://api.typesafe.ai/v1/systemone`
* **Authentication:** `Authorization: Bearer $TYPESAFE_API_KEY`
* **Philosophy:** "Smart switch statement" / Kahneman System 1. Evaluates states against structured questions with sub-second latency (70–500ms) and minimal token overhead ($0.21 per ~8,000–9,000 decisions).

---

## 2. API Contract & Primitives

### 2.1 The Three Primitives

| Primitive | Purpose in SEO-Magus | Return Value |
| :--- | :--- | :--- |
| **`noul`** | Binary decision: Should Page A link to Page B? Is there existing anchor text? | `{ "value": true/false, "confidence": 0.0 - 1.0 }` |
| **`score`** | Ranking decision: How strong is topical/intent relevance? (1–10) | `{ "score": 8.5, "range": [1, 10] }` |
| **`choice`** | Classification: Assign page to a Pillar Topic / Funnel Stage (1 of N) | `{ "selected": "Email Marketing", "confidence": 0.92 }` |

---

## 3. Sample Payloads

### 3.1 Topic Intent & Pillar Classification (`choice`)

```json
{
  "state": {
    "url": "https://example.com/blog/welcome-email-tips",
    "title": "10 Welcome Email Tips for High Open Rates",
    "h1": "How to Craft Welcome Emails that Engage",
    "excerpt": "When a new subscriber joins your newsletter, sending an automated welcome email is your first impression. Here is how to write subject lines and introductions that convert."
  },
  "questions": [
    {
      "id": "topic_cluster",
      "type": "choice",
      "prompt": "Which primary topical cluster does this article belong to?",
      "options": [
        "Email Marketing Basics",
        "Domain Authentication & Deliverability",
        "Automation & Workflows",
        "List Growth & Lead Generation",
        "E-commerce Strategy"
      ]
    },
    {
      "id": "content_type",
      "type": "choice",
      "prompt": "What role does this page serve in the site architecture?",
      "options": ["Pillar Guide", "Support Post", "Money Page", "Case Study / Misc"]
    }
  ]
}
```

### 3.2 Pairwise Link Qualification (`noul` + `score`)

This is the exact check executed 8,790 times in Borja's benchmark:

```json
{
  "state": {
    "source_page": {
      "url": "https://example.com/blog/welcome-email-tips",
      "paragraph": "Once you have nailed your subject line, you need to set up a sequence of 3 to 5 emails to nurture leads over their first two weeks."
    },
    "target_page": {
      "url": "https://example.com/blog/welcome-sequence-guide",
      "title": "The Complete Guide to Automated Welcome Sequences",
      "topic": "Step-by-step tutorial on building multi-day onboarding email sequences."
    }
  },
  "questions": [
    {
      "id": "has_legitimate_contextual_reason",
      "type": "noul",
      "prompt": "Does the source paragraph have a natural educational reason to link to the target page without feeling forced or irrelevant?"
    },
    {
      "id": "candidate_anchor_present",
      "type": "noul",
      "prompt": "Does the source paragraph already contain words or phrases that can serve as natural anchor text for this target page?"
    },
    {
      "id": "relevance_score",
      "type": "score",
      "scale": [1, 10],
      "prompt": "Score the semantic fit between the source paragraph context and the target page value proposition."
    }
  ]
}
```

**Response Example:**
```json
{
  "results": {
    "has_legitimate_contextual_reason": {
      "value": true,
      "confidence": 0.96
    },
    "candidate_anchor_present": {
      "value": true,
      "confidence": 0.91
    },
    "relevance_score": {
      "score": 9.2
    }
  },
  "latency_ms": 112
}
```

---

## 4. The Cascade Workflow: Jev $\rightarrow$ Auxiliary AI

```
                        +----------------------+
                        | Candidate Pair (A, B)|
                        +----------+-----------+
                                   |
                                   v
                        +----------------------+
                        |   Jev System One     |
                        |   - 2x Noul Checks   |
                        |   - 1x Score Check   |
                        +----------+-----------+
                                   |
                        Pass? (Noul=true & Score>=7.5)
                        /                      \
                     Yes                        No
                      |                          |
                      v                          v
          +-----------------------+      +---------------+
          | Auxiliary Frontier AI |      | Discard Pair  |
          | (Claude / Gemini)     |      | (Reject link) |
          | - Exact sentence diff |      +---------------+
          | - Contextual anchor   |
          +-----------------------+
```

### Auxiliary AI Prompt Spec:
When a pair passes Jev's filter, the auxiliary model receives:
1. `source_url` & `target_url`
2. `existing_sentence`
3. `target_title` & `reader_value_proposition`

**Auxiliary LLM Task:**
Return JSON:
```json
{
  "original_sentence": "Once you have nailed your subject line, you need to set up a sequence of 3 to 5 emails to nurture leads over their first two weeks.",
  "updated_sentence": "Once you have nailed your subject line, you need to set up a [sequence of 3 to 5 welcome emails](https://example.com/blog/welcome-sequence-guide) to nurture leads over their first two weeks.",
  "anchor_text": "sequence of 3 to 5 welcome emails",
  "rationale": "Directly guides the reader to execute the sequence mentioned in the sentence."
}
```
