#!/data/data/com.termux/files/usr/bin/bash
# Instala as dependências no Termux (Android) e agenda o coletor em segundo plano.
# Uso (dentro da pasta do coletor):  bash instalar-termux.sh [minutos_entre_verificacoes]   # padrão: 5
# A cada verificação, só coletam as fontes cujo intervalo_min já venceu.
set -euo pipefail

MIN="${1:-5}"
PASTA="$(cd "$(dirname "$0")" && pwd)"

pkg update -y
pkg install -y python git openssh cronie termux-services termux-api

mkdir -p "$PASTA/dados"

# Agenda: verifica a cada N minutos; a saída fica em dados/cron.log.
# git pull traz os vínculos novos que você cadastrou pelo painel; verificar = corretor (Gemini) antes de publicar.
LINHA="*/$MIN * * * * cd $PASTA && (git pull -q --ff-only || true; python3 coletor.py coletar && python3 coletor.py verificar && python3 coletor.py publicar) >> $PASTA/dados/cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'coletor.py' || true; echo "$LINHA" ) | crontab -

# Inicia o agendador junto com o Termux.
sv-enable crond || true

# Reinicia sozinho depois que o celular religar (precisa do app Termux:Boot instalado).
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/coletor.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
crond
EOF
chmod +x "$HOME/.termux/boot/coletor.sh"

termux-wake-lock || true
crond 2>/dev/null || true

echo
echo "Pronto: verificação a cada $MIN min. Agenda atual:"
crontab -l
echo
echo "Chaves (Gemini etc.): copie .env.exemplo para .env e preencha."
echo "Falta, no Android: Configurações > Apps > Termux > Bateria > Sem restrições."
