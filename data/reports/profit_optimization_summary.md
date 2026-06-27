profit_optimization=simulation_only_no_fake_gain
source_dir=C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer
best_config=no_trade_baseline
best_train_pnl_usdc=0.000000
best_validation_pnl_usdc=0.000000
best_holdout_pnl_usdc=0.000000
best_total_net_pnl_usdc=0.000000
best_selected_events=0
strategies:
- no_trade_baseline: train=0.000000 validation=0.000000 holdout=0.000000 total=0.000000 selected=0 overfit_rejected=false
- open_only_fresh_edge25: train=-1.765448 validation=-0.420000 holdout=-0.420000 total=-2.605448 selected=44 overfit_rejected=false
- open_only_fresh_edge60: train=-0.060000 validation=0.000000 holdout=0.000000 total=-0.060000 selected=1 overfit_rejected=false
- consensus3_edge25: train=-0.517464 validation=-0.127409 holdout=-0.120000 total=-0.764873 selected=16 overfit_rejected=false
- strict_latency_edge40: train=0.000000 validation=0.000000 holdout=0.000000 total=0.000000 selected=0 overfit_rejected=false
- no_micro_edge40: train=-1.926111 validation=-0.738147 holdout=-0.779861 total=-3.444119 selected=59 overfit_rejected=false
- high_edge_only: train=0.000000 validation=0.000000 holdout=0.000000 total=0.000000 selected=0 overfit_rejected=false
no_trade_baseline_pnl_usdc=0.000000
anti_overfit=validation_and_holdout_checked
execution=forbidden
paper_simulation_only=true
profit_guarantee=false