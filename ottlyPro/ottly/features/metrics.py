from ..core.repo import get_user_counters, get_global_counters

def user_totals_text(user_id:int) -> tuple[str, str, int, int]:
    total, env_total = get_user_counters(user_id)
    return (f"Total Messages Sent: {total}",
            f"Ads Message Total Sent (ENV_AD_MESSAGE): {env_total}",
            total, env_total)

def global_totals() -> tuple[int,int]:
    return get_global_counters()
