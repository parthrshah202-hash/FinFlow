import json
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from src.logging_config import get_logger
from src.load import get_engine, prototype_embeddings
from src.mapper import _get_model

logger = get_logger()

def seed_prototype_embeddings(engine: Engine) -> None:
    seeds_path = Path(__file__).resolve().parent.parent / "config" / "prototype_seeds.json"
    with seeds_path.open("r", encoding="utf-8") as handle:
        seed_payload = json.load(handle)

    if not isinstance(seed_payload, dict):
        raise TypeError(f"Prototype seed config must be a dict: {seeds_path}")

    model = _get_model()
    pairs = [
        (canonical_field, prototype_text)
        for canonical_field, prototype_texts in seed_payload.items()
        for prototype_text in prototype_texts
    ]

    inserted_count = 0
    skipped_count = 0

    for canonical_field, prototype_text in pairs:
        embedding = model.encode([prototype_text], convert_to_numpy=True)[0]
        try:
            with engine.begin() as connection:
                connection.execute(
                    prototype_embeddings.insert(),
                    {
                        "canonical_field": canonical_field,
                        "prototype_text": prototype_text,
                        "embedding": embedding,
                    },
                )
        except IntegrityError:
            logger.info("Already seeded: %s -> %s, skipping", canonical_field, prototype_text)
            skipped_count += 1
            continue
        except Exception:
            logger.error("Failed to seed prototype: %s -> %s", canonical_field, prototype_text)
            raise

        inserted_count += 1

    logger.info(
        "Seed summary: %s rows newly inserted, %s rows skipped as already seeded",
        inserted_count,
        skipped_count,
    )


if __name__ == "__main__":
    engine = get_engine()
    seed_prototype_embeddings(engine)
