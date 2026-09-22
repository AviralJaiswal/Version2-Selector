import csv
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

OUT = Path(__file__).parent / "generated"
fake = Faker("en_IN")
random.seed(7)
cities = [("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"), ("Bengaluru", "Karnataka"),
          ("Chennai", "Tamil Nadu"), ("Hyderabad", "Telangana"), ("Delhi", "Delhi"),
          ("Noida", "Uttar Pradesh"), ("Kolkata", "West Bengal"), ("Ahmedabad", "Gujarat"),
          ("Jaipur", "Rajasthan"), ("Lucknow", "Uttar Pradesh"), ("Kochi", "Kerala"),
          ("Indore", "Madhya Pradesh"), ("Surat", "Gujarat"), ("Nagpur", "Maharashtra")]


def write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(exist_ok=True)
    with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
        writer.writeheader(); writer.writerows(rows)


def generate() -> None:
    addresses = []
    fdhs = []
    for i in range(2000):
        city, state = random.choice(cities); fdh = f"FDH-{i % 80:03d}"
        if fdh not in fdhs: fdhs.append(fdh)
        addresses.append({"pincode": f"{random.randint(110001, 799999):06d}", "city": city, "state": state,
                          "region_type": random.choice(["urban", "suburban", "rural"]), "fdh_id": fdh,
                          "mst_id": f"MST-{i % 120:03d}", "olt_id": f"OLT-{i % 250:03d}",
                          "serviceable": random.random() < .72, "max_speed_available_mbps": random.choice([50, 100, 200, 500, 1000])})
    plans = [{"plan_id": f"PLAN-{i:02d}", "name": name, "speed_mbps": speed, "price_inr": price,
              "type": typ, "min_speed_required": max(0, speed // 2)}
             for i, (name, speed, price, typ) in enumerate([
                 ("Fiber Starter", 50, 499, "fiber"), ("Fiber Value", 100, 699, "fiber"),
                 ("Fiber Pro", 200, 899, "fiber"), ("Fiber Max", 500, 1299, "fiber"),
                 ("Fiber Ultra", 1000, 1799, "fiber"), ("Copper Basic", 25, 399, "copper"),
                 ("Wireless Home", 50, 599, "wireless"), ("Wireless Plus", 100, 799, "wireless"),
                 ("Work From Home", 200, 999, "fiber"), ("Family Stream", 500, 1399, "fiber")])]
    customers = [{"customer_id": f"CUST-{i:04d}", "name": fake.name(), "phone": fake.msisdn()[:10],
                  "email": fake.email(), "existing_pincode": addresses[i]["pincode"]} for i in range(200)]
    slots = [{"slot_id": f"SLOT-{fdh}-{day}-{window}", "date": (date.today() + timedelta(days=day)).isoformat(),
              "time_window": window, "fdh_id": fdh, "available": random.random() < .8}
             for fdh in fdhs for day in range(14) for window in ["09:00-12:00", "13:00-16:00", "16:00-19:00"]]
    write("addresses", addresses); write("plans", plans); write("customers", customers); write("appointment_slots", slots)
    write("orders", [])
    print(f"Generated datasets in {OUT}")


if __name__ == "__main__": generate()

