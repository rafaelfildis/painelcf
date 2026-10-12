#!/bin/sh
# Coleta diária do módulo de teses (cron em Linux/macOS).
# Exemplo de crontab (todo dia às 9h, horário de Brasília):
#   0 9 * * * /caminho/para/painelcf/scripts/coleta_diaria.sh
cd "$(dirname "$0")/.." || exit 1
mkdir -p dados
python3 -m painelcf.teses diario >> dados/coleta.log 2>&1
