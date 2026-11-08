#!/usr/bin/env bash
# Installe + lance le noeud Hyperliquid DANS la distro Ubuntu dediee (jamais Salad).
# PAPER / lecture seule : non-validateur, aucune cle, aucun ordre.
set -e

echo "== Noeud Hyperliquid local (Ubuntu dedie) =="

if ! command -v curl >/dev/null 2>&1; then
  echo "Installation de curl (un mot de passe sudo peut etre demande)..."
  sudo apt-get update -y && sudo apt-get install -y curl
fi

mkdir -p ~/hl/data
echo "Telechargement du binaire du noeud..."
curl -fL -o ~/hl-visor https://binaries.hyperliquid.xyz/Mainnet/hl-visor
chmod +x ~/hl-visor
printf '{"chain":"Mainnet"}' > ~/visor.json

echo ""
echo "Donnees (accessibles cote Windows) : \\\\wsl.localhost\\Ubuntu\\root\\hl\\data"
echo "Verifie le README officiel si une erreur de version apparait :"
echo "  https://github.com/hyperliquid-dex/node"
echo ""
echo "Lancement du noeud (laisse ouvert ; Ctrl+C pour arreter)..."
exec ~/hl-visor run-non-validator --write-fills
