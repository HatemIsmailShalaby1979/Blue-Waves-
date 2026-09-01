from __future__ import annotations

import argparse
import json
import sys

from .agents import roster
from .application import BlueWavesApplication
from .config import Settings
from .governance import GovernanceViolation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blue-waves", description="Blue Waves governed content-studio CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="show service health and governance state")
    sub.add_parser("register", help="register Blue Waves as an external Codex client")
    demo = sub.add_parser("demo", help="run a full bilingual contract-test workflow")
    demo.add_argument("--topic", default="How Erlang C turns queue volume into a staffing decision")
    demo.add_argument("--source-url", default=None)
    demo.add_argument("--source-verified", action="store_true", help="owner attests the supplied source has been verified")
    sub.add_parser("review", help="create a KOYOSHU weekly proposal without applying it")
    sub.add_parser("agents", help="show the separate Blue Waves roster")
    sub.add_parser("serve", help="start the local Blue Waves HTTP service")
    cockpit = sub.add_parser("cockpit", help="start the Cockpit web UI")
    cockpit.add_argument("--host", default="0.0.0.0", help="host to bind to")
    cockpit.add_argument("--port", type=int, default=8420, help="port to listen on")
    return parser


def run_demo(app: BlueWavesApplication, topic: str, source_url: str | None, source_verified: bool) -> dict[str, object]:
    registration = app.register()
    ar, en = app.create_bilingual_lesson(
        topic,
        source_url=source_url,
        source_verified=source_verified,
        lesson_id="sprint-0-operator-craft",
    )
    outputs: list[dict[str, object]] = []
    for asset in (ar, en):
        produced = app.fact_check_and_produce(asset)
        if not produced["ready"]:
            raise RuntimeError(f"fact-check blocked {asset.asset_id}: {produced['unsupported_claims']}")
        approved = app.owner_approve(asset)
        published = app.publish(asset, "youtube")
        app.record_metric(asset, "youtube", "watch_time_seconds", 0, source="contract_test_placeholder")
        outputs.append({"asset_id": asset.asset_id, "language": asset.language.value, "approved": approved, "published": published})
    return {"registration": registration, "videos": outputs, "weekly_review": app.weekly_review(), "health": app.health()}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = BlueWavesApplication(Settings.from_env())
    try:
        if args.command == "health":
            result = app.health()
        elif args.command == "register":
            result = app.register()
        elif args.command == "review":
            result = app.weekly_review()
        elif args.command == "agents":
            result = {"tenant_id": app.settings.tenant_id, "agents": roster()}
        elif args.command == "serve":
            from .service import serve
            serve(app)
            return 0
        elif args.command == "cockpit":
            from .service import serve
            serve(app, host=args.host, port=args.port)
            return 0
        else:
            result = run_demo(app, args.topic, args.source_url, args.source_verified)
    except (GovernanceViolation, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
