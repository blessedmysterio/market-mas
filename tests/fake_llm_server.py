"""Фейковый OpenAI-совместимый сервер для тестов: правильные JSON-ответы по схемам агентов + отказы
(429 на 2-м запросе, нет поддержки response_format, <think>-теги, LLM-критик отклоняет без причины)."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
state = {"n": 0, "max_user_chars": 0, "rf_seen": 0}
def answer(system, user):
    try:
        task = json.loads(user.split("\n\nПредыдущий")[0])
    except ValueError:
        return {"status": "ok", "model": "fake"}
    if '"title": "Plan"' in system:
        steps = [{"agent": a, "task": "шаг"} for a in ["market_researcher","scenario_designer","critic","simulation_engineer","analyst","critic","report_writer"]]
        return {"in_scope": True, "reason": "маркетинговый вопрос", "steps": steps}
    if '"title": "ResearchQuery"' in system:
        return {"industry": "telecom", "literature_query": "hub seeding influencers social network"}
    if '"title": "ScenarioSpec"' in system:
        return {"title": "Хабы vs реклама (telecom)", "research_question": task["brief"], "strategies": ["baseline","hub_seeding","mass_media"],
                "budget_kzt": 30000000, "n_agents": 1000, "ba_m": 3, "n_steps": 60, "n_runs": 30, "intervention_step": 5, "shock": None, "assumptions": ["LLM"]}
    if '"title": "ReviewVerdict"' in system:
        return {"target": task["target"], "approved": False, "issues": [{"severity": "error", "field": "style", "message": "мне не нравится"}], "comment": "LLM-критик недоволен"}
    if '"title": "ExperimentPlan"' in system:
        return {"n_runs": 20, "base_seed": 7, "common_random_numbers": True, "rationale": "20 прогонов достаточно"}
    if '"title": "Analysis"' in system:
        comps = task["comparisons"]; means = task["means_pp"]
        best = max(means, key=means.get)
        return {"best_strategy": best, "claims": [{"a": c["a"], "b": c["b"], "delta_pp": c["delta_pp"], "significant": c["p_holm"] < 0.05} for c in comps],
                "interpretation": f"Лучшая стратегия — {best}.", "recommendation": f"Выбрать {best}.", "caveats": ["модель упрощена"]}
    if '"title": "ExecutiveSummary"' in system:
        return {"headline": "LLM: итог эксперимента", "summary": "Краткое резюме от модели.", "next_steps": ["пилот"]}
    return {"status": "ok", "model": "fake"}
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        state["n"] += 1
        if state["n"] == 2:
            self.send_response(429); self.send_header("retry-after", "1"); self.end_headers(); return
        if "response_format" in body:
            state["rf_seen"] += 1
            msg = json.dumps({"error": {"message": "response_format is not supported by this model"}}).encode()
            self.send_response(400); self.end_headers(); self.wfile.write(msg); return
        sysm, user = body["messages"][0]["content"], body["messages"][1]["content"]
        state["max_user_chars"] = max(state["max_user_chars"], len(user))
        content = "<think>рассуждаю...</think>" + json.dumps(answer(sysm, user), ensure_ascii=False)
        out = {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": len(sysm + user) // 4, "completion_tokens": 50}}
        b = json.dumps(out).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass


def start():
    import threading
    state.update(n=0, max_user_chars=0, rf_seen=0)
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"
