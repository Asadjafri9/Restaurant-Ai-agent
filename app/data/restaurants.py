RESTAURANTS = {
    "kababjees": {
        "name": "Kababjees",
        "menu": [
            {"id": 1, "item": "Chicken Biryani", "price_pkr": 450},
            {"id": 2, "item": "Beef Kabab Roll", "price_pkr": 350},
            {"id": 3, "item": "Seekh Kabab (2 pcs)", "price_pkr": 400},
            {"id": 4, "item": "Chicken Karahi (Half)", "price_pkr": 850},
            {"id": 5, "item": "Garlic Naan", "price_pkr": 60},
            {"id": 6, "item": "Raita", "price_pkr": 80},
            {"id": 7, "item": "Chicken Tikka (4 pcs)", "price_pkr": 550},
        ],
    },
    "kfc": {
        "name": "KFC",
        "menu": [
            {"id": 1, "item": "Zinger Burger", "price_pkr": 520},
            {"id": 2, "item": "Hot Wings (6 pcs)", "price_pkr": 650},
            {"id": 3, "item": "Family Bucket (9 pcs)", "price_pkr": 2200},
            {"id": 4, "item": "Fries (Large)", "price_pkr": 350},
            {"id": 5, "item": "Pepsi (1L)", "price_pkr": 200},
            {"id": 8, "item": "Fizz Up Next", "price_pkr": 150},
            {"id": 6, "item": "Krusher", "price_pkr": 380},
            {"id": 7, "item": "Chicken Piece (1 pc)", "price_pkr": 320},
        ],
    },
}


def format_menus_for_prompt() -> str:
    lines = []
    for key, restaurant in RESTAURANTS.items():
        lines.append(f"\n{restaurant['name']} ({key}):")
        for item in restaurant["menu"]:
            lines.append(f"  {item['id']}. {item['item']} — Rs {item['price_pkr']}")
    return "\n".join(lines)
