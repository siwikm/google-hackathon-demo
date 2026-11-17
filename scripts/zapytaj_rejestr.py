"""Ask the registry agent one question from the command line.

    uv run python scripts/zapytaj_rejestr.py "Znajdź umowy powierzenia bez zapisu o termination_data_policy"
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from rejestr_umow.agent import root_agent  # noqa: E402


async def main(question: str) -> None:
    runner = InMemoryRunner(node=root_agent, app_name="rejestr_umow")
    session = await runner.session_service.create_session(app_name="rejestr_umow", user_id="cli")
    message = types.Content(role="user", parts=[types.Part.from_text(text=question)])
    async for event in runner.run_async(user_id="cli", session_id=session.id, new_message=message):
        for call in event.get_function_calls():
            print("→", call.name, json.dumps(call.args, ensure_ascii=False)[:220])
    done = await runner.session_service.get_session(app_name="rejestr_umow", user_id="cli", session_id=session.id)
    wynik = done.state["wynik"]
    print("odpowiedz:", wynik["odpowiedz"])
    print("sql:", wynik["sql"])
    for u in wynik["umowy"]:
        print("  ", u["file_name"], u["status"], [(o["zasada_id"], o["poziom"]) for o in u["odstepstwa"]])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
