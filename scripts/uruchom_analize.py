"""Run the analysis agent on one file from the command line (smoke test without the frontend).

    uv run python scripts/uruchom_analize.py wiedza/demo/umowa_demo_b2b.txt
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from analiza_umowy.agent import root_agent  # noqa: E402
from core.tekst import akapity_z_bajtow, tekst_dla_agenta  # noqa: E402


async def main(path: Path) -> None:
    runner = InMemoryRunner(node=root_agent, app_name="analiza_umowy")
    session = await runner.session_service.create_session(
        app_name="analiza_umowy", user_id="cli", state={"nazwa_pliku": path.name}
    )
    text = tekst_dla_agenta(akapity_z_bajtow(path.name, path.read_bytes()))
    message = types.Content(role="user", parts=[types.Part.from_text(text=text)])
    async for event in runner.run_async(user_id="cli", session_id=session.id, new_message=message):
        for call in event.get_function_calls():
            print("→", call.name, json.dumps(call.args, ensure_ascii=False)[:200])
    done = await runner.session_service.get_session(app_name="analiza_umowy", user_id="cli", session_id=session.id)
    wynik = done.state["wynik"]
    print("score:", wynik["score"]["wartosc"], wynik["score"]["poziom"], "| zapis:", wynik["zapis_rejestru"])
    for r in wynik["ryzyka"]:
        print(f"  {r['id']} {r['poziom']:8} {r['zasada_id']:12} P{r.get('akapit')} | {r['cytat'][:70]}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
