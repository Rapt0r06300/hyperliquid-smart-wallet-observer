# HyperSmart Explorer Observer

L'observer Explorer est experimental et desactive par defaut.

Regles:

- aucun endpoint prive;
- aucune authentification;
- scraping + proxies/rotation autorises (cf. V9 §8);
- gestion intelligente du rate limit (budget de poids par IP);
- import manuel possible;
- action ambigue classee `UNKNOWN`.

Les donnees Explorer sont des observations publiques ou des imports, jamais une source d'execution.
## Docs-to-code checklist

- [x] Explorer remains experimental.
- [x] Scraping + proxy/rotation policy documented (V9 §8).
- [ ] Manual explorer export parser.
- [ ] Provider health status for explorer disabled/default.
- [ ] Tests proving explorer provider is disabled by default.
