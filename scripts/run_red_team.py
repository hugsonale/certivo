#!/usr/bin/env python3
"""
Run Red-Team Test Suite
"""

import asyncio
import sys
import argparse

sys.path.insert(0, 'red_team')

from framework import RedTeamFramework, AttackType
from attacks.replay_attack import ReplayAttackModule
from attacks.video_injection import VideoInjectionModule
from attacks.headless_automation import HeadlessAutomationModule
from attacks.prompt_prediction import PromptPredictionModule
from attacks.device_spoofing import DeviceSpoofingModule
from risk_gate import RiskGate
import asyncpg
import redis.asyncio as redis
import json


async def main(args):
    """Run red-team tests"""
    
    # Initialize
    postgres_pool = await asyncpg.create_pool(
        "postgresql://certivo:certivo@localhost:5432/certivo"
    )
    
    redis_client = await redis.from_url("redis://localhost:6379")
    
    framework = RedTeamFramework(
        api_base_url=args.api_url,
        postgres_pool=postgres_pool,
        redis_client=redis_client
    )
    
    # Register modules
    framework.register_attack_module(AttackType.REPLAY_ATTACK, ReplayAttackModule())
    framework.register_attack_module(AttackType.VIDEO_INJECTION, VideoInjectionModule())
    framework.register_attack_module(AttackType.HEADLESS_AUTOMATION, HeadlessAutomationModule())
    framework.register_attack_module(AttackType.PROMPT_PREDICTION, PromptPredictionModule())
    framework.register_attack_module(AttackType.DEVICE_SPOOFING, DeviceSpoofingModule())
    
    # Run tests
    if args.full_suite:
        summary = await framework.run_full_suite()
    else:
        # Run specific attack
        attack_type = AttackType(args.attack_type)
        result = await framework.run_attack(attack_type, num_attempts=args.attempts)
        summary = {
            "results": {args.attack_type: {"bypass_rate": result.bypass_rate}}
        }
    
    # Save results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\n✅ Results saved to {args.output}")
    
    # Cleanup
    await postgres_pool.close()
    await redis_client.close()
    
    # Exit code
    if summary.get("risk_gate_passed", True):
        return 0
    else:
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run red-team tests")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--full-suite", action="store_true", help="Run full suite")
    parser.add_argument("--attack-type", help="Specific attack type")
    parser.add_argument("--attempts", type=int, default=100, help="Number of attempts")
    parser.add_argument("--output", help="Output file for results")
    
    args = parser.parse_args()
    
    sys.exit(asyncio.run(main(args)))