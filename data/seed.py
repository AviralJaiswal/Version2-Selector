import csv
import argparse
import sys
from datetime import date
from pathlib import Path

# Make the project root importable so "app.*" imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, text

from app.database import Base, SessionLocal, engine
from app.models import Address, AppointmentSlot, Customer, Order, Plan


# CSV data directory
DATA = Path(__file__).parent / "generated"


def rows(name):
    """Read a generated CSV file and return its rows as dictionaries."""
    with (DATA / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seed(reset: bool = False) -> None:
    # Optionally drop and recreate the demo tables
    if reset:
        Base.metadata.drop_all(engine)


    # Create tables if they don't already exist
    Base.metadata.create_all(engine)

    db = SessionLocal()

    try:
        # Remove existing seed data
        for model in [
            Order,
            AppointmentSlot,
            Customer,
            Plan,
            Address,
        ]:
            db.execute(delete(model))

        # ---------------------------------------------------------
        # ADDRESSES
        # CSV:
        # pincode,area,district,state,region_type,fdh_id,mst_id,
        # mst_id,olt_id,serviceable,max_speed_available_mbps
        #
        # Database/model:
        # pincode,city,state,region_type,fdh_id,mst_id,olt_id,
        # serviceable,max_speed_available_mbps
        #
        # area -> city
        # district is currently not stored because Address has no
        # district column.
        # ---------------------------------------------------------
        address_data = [
            {
                "pincode": r["pincode"],
                "city": r["area"],
                "state": r["state"],
                "region_type": r["region_type"],
                "fdh_id": r["fdh_id"],
                "mst_id": r["mst_id"],
                "olt_id": r["olt_id"],
                "serviceable": r["serviceable"].strip().lower() == "true",
                "max_speed_available_mbps": int(
                    r["max_speed_available_mbps"]
                ),
            }
            for r in rows("addresses")
        ]

        db.bulk_insert_mappings(Address, address_data)

        # ---------------------------------------------------------
        # PLANS
        # ---------------------------------------------------------
        plan_data = [
            {
                **r,
                "speed_mbps": int(r["speed_mbps"]),
                "price_inr": int(r["price_inr"]),
                "min_speed_required": int(r["min_speed_required"]),
            }
            for r in rows("plans")
        ]

        db.bulk_insert_mappings(Plan, plan_data)

        # ---------------------------------------------------------
        # CUSTOMERS
        # ---------------------------------------------------------
        customers_csv = DATA / "customers.csv"
        if customers_csv.exists():
            customer_data = [
                {
                    **r,
                    "current_plan_id": r["current_plan_id"] or None,
                    "joined_on": date.fromisoformat(r["joined_on"]) if r.get("joined_on") else None,
                }
                for r in rows("customers")
            ]
            db.bulk_insert_mappings(Customer, customer_data)

        # ---------------------------------------------------------
        # APPOINTMENT SLOTS
        # ---------------------------------------------------------
        appointment_data = [
            {
                **r,
                "date": date.fromisoformat(r["date"]),
                "available": r["available"].strip().lower() == "true",
            }
            for r in rows("appointment_slots")
        ]

        db.bulk_insert_mappings(
            AppointmentSlot,
            appointment_data,
        )

        # Save everything
        db.commit()

    except Exception:
        # Roll back the transaction if anything fails
        db.rollback()
        raise

    finally:
        db.close()

    print("Database seeded successfully")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed generated CSV data into PostgreSQL"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate demo tables before seeding",
    )

    args = parser.parse_args()

    seed(reset=args.reset)