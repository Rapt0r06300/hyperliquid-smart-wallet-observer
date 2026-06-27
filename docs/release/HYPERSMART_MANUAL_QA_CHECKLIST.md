# HyperSmart Manual QA Checklist

- Run `python -m hyper_smart_observer.app.main --runtime-check`.
- Confirm DB path is `data/hypersmart_observer.sqlite3`.
- Confirm legacy DB in `logs/` is only reported, not archived.
- Run `python -m hyper_smart_observer.app.main --dashboard-export`.
- Open `data/dashboard/hypersmart_dashboard.html`.
- Confirm no trade/buy/sell/execute buttons.
- Run `python -m hyper_smart_observer.app.main --audit-safety`.
- Run the clean archive script.
