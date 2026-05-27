from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription, SubscriptionPlanner


def test_ws_limit_ten_user_subscriptions():
    subs = [Subscription(StreamType.USER_FILLS, user="0x" + f"{i:040x}") for i in range(11)]

    plan = SubscriptionPlanner(AppConfig(ws_max_user_subscriptions=10)).plan(subs)

    assert len([sub for sub in plan.accepted if sub.user]) == 10
    assert plan.rejected
