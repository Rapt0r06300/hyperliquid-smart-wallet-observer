# HyperSmart no_trade_report

Mode: observation / paper mock USDC uniquement. Aucun ordre reel.

## Synthese
- NETWORK_READ_DISABLED: 1

## Details
### NETWORK_READ_DISABLED
- Observe: copy-run lance sans lecture reseau explicite.
- Pourquoi: Aucun appel /info ou WS n'est lance sans accord explicite.
- Donnee manquante: autorisation explicite --network-read
- Risque: INFO
- Composant: copy_mode
- Action suivante: Relancer avec --network-read pour une collecte read-only bornee.
