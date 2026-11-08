#!/usr/bin/env bash
# Relance le noeud Hyperliquid DEJA installe dans la distro Ubuntu dediee (jamais Salad).
# PAPER / lecture seule.
set -e

if [ ! -x ~/hl-visor ]; then
  echo "Binaire ~/hl-visor introuvable. Lance d'abord 'Installer Noeud HL.cmd'."
  exit 1
fi

mkdir -p ~/hl/data
echo "Noeud en cours (laisse ouvert ; Ctrl+C pour arreter)..."
exec ~/hl-visor run-non-validator --write-fills
