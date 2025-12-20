def slice_page(items: list, page: int, per_page: int = 8):
    start = page * per_page
    end = start + per_page
    return items[start:end], max(0, page-1), page+1, len(items), (len(items)+per_page-1)//per_page
