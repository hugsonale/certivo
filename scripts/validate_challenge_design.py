#!/usr/bin/env python3
"""
Validate Challenge Design Acceptance Criteria
"""

import sys
sys.path.insert(0, 'services/shared')

from challenge_templates import ChallengeTemplateLibrary
from challenge_generator import ChallengeGenerator, AccessibilityProfile


def main():
    """Validate challenge design acceptance criteria"""
    
    print("="*60)
    print("CHALLENGE DESIGN VALIDATION")
    print("="*60)
    
    library = ChallengeTemplateLibrary()
    generator = ChallengeGenerator()
    
    # Criterion 1: At least 12 templates
    template_count = library.get_count()
    
    print(f"\n✓ Criterion 1: Template Count")
    print(f"  Required: ≥ 12 templates")
    print(f"  Actual: {template_count} templates")
    print(f"  Status: {'✅ PASS' if template_count >= 12 else '❌ FAIL'}")
    
    # List templates
    templates = library.get_all_templates()
    print(f"\n  Templates:")
    for i, template in enumerate(templates, 1):
        print(f"    {i:2d}. {template.template_id}: {template.name}")
    
    # Criterion 2: Composite challenges
    composite = [t for t in templates if len(t.actions) >= 2]
    print(f"\n✓ Composite Challenges")
    print(f"  Count: {len(composite)}")
    print(f"  Examples: {', '.join(t.template_id for t in composite[:3])}")
    
    # Criterion 3: Accessibility alternatives
    no_motion = library.get_templates_by_accessibility(requires_motion=False)
    print(f"\n✓ Accessibility Alternatives")
    print(f"  Templates without motion: {len(no_motion)}")
    print(f"  Status: {'✅ PASS' if len(no_motion) >= 2 else '❌ FAIL'}")
    
    # Criterion 4: Locale support
    from locale_prompts import LocalePrompts
    locales = LocalePrompts.get_supported_locales()
    print(f"\n✓ Locale Support")
    print(f"  Supported languages: {len(locales)}")
    print(f"  Locales: {', '.join(locales[:7])}...")
    
    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)
    
    checks = [
        ("Template count ≥ 12", template_count >= 12),
        ("Composite challenges", len(composite) >= 5),
        ("Accessibility alternatives", len(no_motion) >= 2),
        ("Locale support", len(locales) >= 10),
    ]
    
    all_pass = all(result for _, result in checks)
    
    for check, result in checks:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {check}")
    
    print("="*60)
    
    if all_pass:
        print("✅ ALL ACCEPTANCE CRITERIA MET")
        return 0
    else:
        print("❌ SOME CRITERIA NOT MET")
        return 1


if __name__ == "__main__":
    sys.exit(main())