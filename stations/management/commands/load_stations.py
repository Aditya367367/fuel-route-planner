import csv
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stations.models import Station
from stations.services.gazetteer import load_gazetteer, normalize
from stations.services.store import reset_store

GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip"
)


class Command(BaseCommand):
    help = "Load the fuel price CSV, drop duplicates and give each station city-level coordinates."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(Path(settings.BASE_DIR) / "data" / "fuel-prices-for-be-assessment.csv"))
        parser.add_argument("--gazetteer", help="path to an already downloaded Census places zip")
        parser.add_argument("--gazetteer-url", default=GAZETTEER_URL)

    def handle(self, *args, **opts):
        # The CSV lists some stations more than once. Keep the cheapest price per location.
        unique = {}
        with open(opts["csv"], newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                key = (int(row["OPIS Truckstop ID"]), row["Address"].strip(), row["City"].strip(), row["State"].strip())
                price = float(row["Retail Price"])
                if key not in unique or price < unique[key]["price"]:
                    unique[key] = {
                        "name": row["Truckstop Name"].strip(),
                        "rack_id": int(row["Rack ID"]) if row["Rack ID"] else None,
                        "price": price,
                    }
        self.stdout.write(f"{len(unique)} unique stations")

        if opts["gazetteer"]:
            places = load_gazetteer(path=opts["gazetteer"])
        else:
            self.stdout.write("Downloading the Census gazetteer...")
            resp = requests.get(opts["gazetteer_url"], timeout=60)
            if resp.status_code != 200:
                raise CommandError(f"Download failed ({resp.status_code}). Pass --gazetteer PATH instead.")
            places = load_gazetteer(zip_bytes=resp.content)

        stations, unmatched = [], []
        for (opis_id, address, city, state), info in unique.items():
            coords = places.get((state, normalize(city)))
            if coords is None:
                unmatched.append(f"{city}, {state}")
            stations.append(Station(
                opis_id=opis_id, address=address, city=city, state=state,
                name=info["name"], rack_id=info["rack_id"], price=info["price"],
                latitude=coords[0] if coords else None,
                longitude=coords[1] if coords else None,
            ))

        with transaction.atomic():
            Station.objects.all().delete()
            Station.objects.bulk_create(stations, batch_size=1000)
        reset_store()

        placed = len(stations) - len(unmatched)
        self.stdout.write(self.style.SUCCESS(f"Saved {len(stations)} stations, {placed} with coordinates"))
        if unmatched:
            sample = "; ".join(sorted(set(unmatched))[:15])
            self.stdout.write(f"{len(unmatched)} not found in the gazetteer (left out of routing): {sample}")
