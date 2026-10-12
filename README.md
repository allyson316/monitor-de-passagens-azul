# Monitor de passagens Azul

Scripts de consulta de ofertas da Azul. O monitor agendado (`scripts/azul_monitor_todos.py`) consulta ida e volta entre Campinas e Recife, Natal e Juazeiro do Norte, com limite de 20.000 pontos, e envia os alertas ao Telegram. Os quatro scripts individuais consultam as rotas da Europa em reais ou milhas.

## Execução

```sh
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
cp scripts/telegram_config.example.json scripts/telegram_config.json
chmod 600 scripts/telegram_config.json
python3 scripts/azul_monitor_todos.py
```

Preencha o token e os destinatários em `scripts/telegram_config.json`. Esse arquivo é local e ignorado pelo Git. Na migração do Mac atual, a configuração e as dependências existentes foram preservadas.

## Agendamento no macOS

O agendamento usa **launchd**, a cada 7.200 segundos (2 horas), e também roda quando o agente é carregado. O arquivo instalado é `~/Library/LaunchAgents/com.azulalert.monitor.plist`.

O plist desta máquina aponta para:

- Script: `/Users/allyson316/projetos/busca-passagens/monitor-de-passagens-azul/scripts/azul_monitor_todos.py`
- Diretório de trabalho: `/Users/allyson316/projetos/busca-passagens/monitor-de-passagens-azul/scripts`
- Python: `/usr/bin/python3`, com o `PYTHONPATH` já usado pelo agendamento anterior.
- Saída: `/tmp/azul_monitor.log`
- Erros: `/tmp/azul_monitor_err.log`

Para reinstalar após ajustar os caminhos no plist (o recarregamento executa o monitor):

```sh
plutil -lint scripts/com.azulalert.monitor.plist
launchctl bootout "gui/$(id -u)/com.azulalert.monitor"
cp scripts/com.azulalert.monitor.plist ~/Library/LaunchAgents/com.azulalert.monitor.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.azulalert.monitor.plist
launchctl print "gui/$(id -u)/com.azulalert.monitor"
```

Os logs históricos em `scripts/azul_monitor_logs/` foram preservados localmente e são ignorados pelo Git.
