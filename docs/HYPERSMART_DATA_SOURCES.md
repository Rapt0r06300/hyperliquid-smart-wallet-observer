# HyperSmart Data Sources

HyperSmart uses a provider registry. Defaults are conservative:

- `LocalCacheProvider`: enabled, no network.
- `OfficialInfoProvider`: disabled until explicit `--network-read`.
- `OfficialWsProvider`: disabled until explicit bounded command.
- `ExplorerPublicProvider`: disabled by default, no aggressive scraping.
- `ThirdPartyProvider`: disabled by default, no API key required.

Command:

```powershell
python -m hl_observer research-data-sources
```

