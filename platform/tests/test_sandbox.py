from app.sandbox import run_simulation
from tests.conftest import T0


def test_sandbox_simulation_end_to_end(client, partner_key):
    out = run_simulation(client, partner_key[1], now_ms=T0)
    assert out["attestation_verified"] is True
    bob = [o for (i, who, c, o) in out["timeline"] if who == "bob"]
    alice = [o for (i, who, c, o) in out["timeline"] if who == "alice"]
    assert set(alice) == {"accept"}
    assert bob[:6] == ["accept"] * 6 and bob[6] == "fallback" and set(bob[7:]) == {"reject"}
    parts = {p["participant_reference"]: p
             for p in out["end"]["attestation"]["payload"]["participants"]}
    assert parts["bob"]["reject_transitions"] == 1 and parts["alice"]["reject_transitions"] == 0
