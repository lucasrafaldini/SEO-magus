# Issue 5: Add Local LLM Fallback (Ollama / Llama.cpp) for Offline System 1 Decision Making

**Labels:** `hacktoberfest`, `ai-engine`, `enhancement`  
**Difficulty:** Intermediate  

---

### Description
While TypeSafe Jev provides sub-second cloud decisions and the current codebase includes a fast heuristic simulation mode, many developers and privacy-sensitive teams want to run `SEO-magus` completely offline using local open-weight models (e.g., Llama 3.2 3B, Mistral Nemo, Qwen 2.5) via **Ollama**.

### Requirements
1. **Ollama Engine Provider in `src/engines/local_llm.py`:**
   - Connect to local Ollama daemon (`http://localhost:11434/api/generate` or `api/chat`).
   - Use structured outputs / JSON format mode to answer `noul` (boolean), `score` (integer 1-10), and `choice` questions.
2. **Configuration Support:**
   - In `config/config.example.yaml`, allow selecting `provider: "ollama"` and specifying `model: "llama3.2:3b"`.
3. **Graceful Fallback:**
   - If Ollama is not running on port 11434, gracefully notify the user or fall back to heuristic simulation.
4. **Unit Tests:** Add mocked tests in `tests/test_local_llm.py`.

### How to Get Started
- Look at `src/engines/jev_client.py` and `src/engines/auxiliary_ai.py`.
- Ollama API documentation: https://github.com/ollama/ollama/blob/main/docs/api.md
