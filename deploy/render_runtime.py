from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_service(module: dict) -> str:
    title = module["title"]
    module_dir = module["module_dir"]
    port = int(module["port"])
    return (
        "[Unit]\n"
        f"Description={title}\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory=/opt/rtps/{module_dir}\n"
        "Environment=WEB_HOST=0.0.0.0\n"
        f"Environment=WEB_PORT={port}\n"
        f"ExecStart=/usr/bin/python3 /opt/rtps/{module_dir}/app.py\n"
        "Restart=always\n"
        "RestartSec=2\n"
        "User=root\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def render_nginx(modules: dict[str, dict]) -> str:
    lines = [
        "server {",
        "    listen 80;",
        "    listen 443 ssl http2;",
        "    server_name yrtps.ru www.yrtps.ru;",
        "",
        "    ssl_certificate /etc/letsencrypt/live/yrtps.ru/fullchain.pem;",
        "    ssl_certificate_key /etc/letsencrypt/live/yrtps.ru/privkey.pem;",
        "    ssl_protocols TLSv1.2 TLSv1.3;",
        "    ssl_prefer_server_ciphers on;",
        "",
    ]

    ordered_keys = ["grafik_ppr", "spravochnik", "zamer_kp", "alsn", "tabel", "edu"]
    for key in ordered_keys:
        module = modules[key]
        port = int(module["port"])
        route = module["route"]
        path = route["path"]

        if route["kind"] == "split":
            exact_proxy_path = route.get("exact_proxy_path", path)
            lines.extend(
                [
                    f"    location = {path} {{",
                    f"        proxy_pass http://127.0.0.1:{port}{exact_proxy_path};",
                    "        proxy_set_header Host $host;",
                    "        proxy_set_header X-Real-IP $remote_addr;",
                    "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                    "        proxy_set_header X-Forwarded-Proto $scheme;",
                    "    }",
                    "",
                    f"    location {path}/ {{",
                    f"        proxy_pass http://127.0.0.1:{port}/;",
                    "        proxy_set_header Host $host;",
                    "        proxy_set_header X-Real-IP $remote_addr;",
                    "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                    "        proxy_set_header X-Forwarded-Proto $scheme;",
                    "    }",
                    "",
                ]
            )
            continue

        lines.extend(
            [
                f"    location {path} {{",
                f"        proxy_pass http://127.0.0.1:{port};",
                "        proxy_set_header Host $host;",
                "        proxy_set_header X-Real-IP $remote_addr;",
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                "        proxy_set_header X-Forwarded-Proto $scheme;",
                "    }",
                "",
            ]
        )

    main_port = int(modules["web_main"]["port"])
    lines.extend(
        [
            "    location / {",
            f"        proxy_pass http://127.0.0.1:{main_port};",
            "        proxy_set_header Host $host;",
            "        proxy_set_header X-Real-IP $remote_addr;",
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "        proxy_set_header X-Forwarded-Proto $scheme;",
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render RTPS runtime configs from deploy/modules.json")
    parser.add_argument("--modules-json", default="deploy/modules.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--nginx-file", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    modules_path = (repo_root / args.modules_json).resolve()
    modules = json.loads(modules_path.read_text(encoding="utf-8"))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for module in modules.values():
        service_name = module["service"]
        (output_dir / service_name).write_text(render_service(module), encoding="utf-8")

    nginx_path = Path(args.nginx_file)
    nginx_path.parent.mkdir(parents=True, exist_ok=True)
    nginx_path.write_text(render_nginx(modules), encoding="utf-8")


if __name__ == "__main__":
    main()
