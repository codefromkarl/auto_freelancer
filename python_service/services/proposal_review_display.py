"""Pure comparison presentation, usable by QQ without trading credentials or DB imports."""


def review_summary(review: dict) -> str:
    data = review['benchmark']
    if data['status'] != 'ready':
        return '竞标对比：资料未就绪，需人工核对'
    median = (data.get('price') or {}).get('median')
    price = f"中位价 {median:g} {data['currency']}" if median else '无有效公开报价'
    premium = f"，本稿 {review['premium_pct']:+g}%" if review.get('premium_pct') is not None else ''
    return f"竞标对比：{data['visible_count']} 份公开稿，{price}{premium}；需核对范围/证据"
