from game.skills.base import Skill, SkillAction, register_skill

COOKING = Skill(
    id="COOKING",
    name="Cooking",
    location_ids=["town"],
    actions={
        "shrimp": SkillAction(
            id="shrimp", name="Cook shrimp", level_req=1, xp=12.0,
            cooldown=3, consumes={"raw_shrimp": 1}, produces="cooked_shrimp",
            base_success=0.6, fail_produces="burnt_food",
        ),
        "trout": SkillAction(
            id="trout", name="Cook trout", level_req=15, xp=30.0,
            cooldown=4, consumes={"raw_trout": 1}, produces="cooked_trout",
            base_success=0.4, fail_produces="burnt_food",
        ),
    },
)

register_skill(COOKING)
