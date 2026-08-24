"""Tests for credential redaction in unattended memory writes (issue #113).

The sweep that motivated this found two real leaks (a Firebase web key, an
`nsk-` key) and fifteen false positives from a bare `password` word match — so
these tests weight precision as heavily as recall. Every "survives" case below
is a string that actually appeared in the live store.

No fixture here is a real credential. Values are assembled at import time from
harmless parts: a literal secret in a public repo would trip GitHub push
protection, and pasting the very keys this module exists to erase would be
self-defeating.
"""

from neurostack.redact import REDACTION_MARKER, redact_secrets

# Same shape as the two values found in the live DB, none of their characters.
FIREBASE_KEY = "AIza" + "Sy" + "B" * 33
NSK_KEY = "nsk-" + "Q" * 43


class TestSecretsMasked:
    def test_google_api_key_keeps_prefix_drops_value(self):
        out, kinds = redact_secrets(f"apiKey: {FIREBASE_KEY},")
        assert FIREBASE_KEY not in out
        assert out == f"apiKey: AIza{REDACTION_MARKER},"
        assert kinds == ["google-api-key"]

    def test_neurostack_key(self):
        out, kinds = redact_secrets(f"export NEUROSTACK_API_KEY={NSK_KEY}")
        assert NSK_KEY not in out
        assert out.endswith(f"nsk-{REDACTION_MARKER}")
        assert kinds == ["neurostack-api-key"]

    def test_stripe_secret_and_restricted_keys(self):
        out, kinds = redact_secrets(
            "sk_" + "live_" + "9" * 24 + " and rk_" + "live_" + "9" * 24
        )
        assert "9" * 24 not in out
        assert kinds == ["stripe-secret-key", "stripe-secret-key"]

    def test_github_slack_openai_jwt_tokens(self):
        secrets = [
            "ghp_" + "a" * 36,
            "xox" + "b-" + "1" * 12 + "-" + "c" * 24,
            "sk-" + "proj-" + "b" * 40,
            "eyJ" + "hbGciOiJIUzI1NiJ9." + "e" * 24 + "." + "f" * 24,
        ]
        for secret in secrets:
            out, kinds = redact_secrets(f"token is {secret}")
            assert secret not in out, secret
            assert kinds, secret

    def test_private_key_block_removed_whole(self):
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA1234\nabcd\n"
            "-----END RSA PRIVATE KEY-----"
        )
        out, kinds = redact_secrets(f"key:\n{text}\ndone")
        assert "MIIEowIBAAKCAQEA1234" not in out
        assert out == f"key:\n{REDACTION_MARKER}\ndone"
        assert kinds == ["private-key"]

    def test_bearer_token_masked_but_word_kept(self):
        out, _ = redact_secrets("Authorization: Bearer abcdefghij0123456789ABCDEFGH")
        assert "abcdefghij0123456789ABCDEFGH" not in out
        assert "Bearer " in out

    def test_password_assignment_masked(self):
        out, kinds = redact_secrets('password = "hunter2-correct-horse"')
        assert "hunter2-correct-horse" not in out
        assert kinds == ["password-assignment"]

    def test_multiple_kinds_in_one_text(self):
        out, kinds = redact_secrets(f"{FIREBASE_KEY} then {NSK_KEY}")
        assert FIREBASE_KEY not in out and NSK_KEY not in out
        assert set(kinds) == {"google-api-key", "neurostack-api-key"}


class TestNonSecretsSurvive:
    def test_bare_mentions_untouched(self):
        # Every one of these is a real live-store string the sweep flagged.
        for text in [
            "No Firebase API key in the build at all.",
            "Firebase `auth/invalid-api-key` — the frontend config has the wrong key.",
            "The commit reverted to hardcoding a password, an unnecessary regression.",
            "apiKey: import.meta.env.VITE_FIREBASE_API_KEY,",
            "VITE_FIREBASE_API_KEY=your-firebase-api-key",
            "It checks `_cc.cloud_api_key` at line 1048.",
            "password blacklist enforced at signup",
        ]:
            out, kinds = redact_secrets(text)
            assert out == text, text
            assert kinds == [], text

    def test_password_references_are_not_values(self):
        # `PASSWORD=${OPERATIONS_APP_PASSWORD}` is a real live-store line.
        for text in [
            "DB_PASSWORD=${OPERATIONS_APP_PASSWORD}",
            "password=%DEPLOY_PASSWORD%",
            "password: {password}",
            "password = <redacted-by-ci>",
            "password=your-password-here",
            "password = os.environ['DB_PW']",
            "PASSWORD=OPERATIONS_APP_PASSWORD",
        ]:
            out, kinds = redact_secrets(text)
            assert out == text, text
            assert kinds == [], text

    def test_aws_documentation_example_allowlisted(self):
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        out, kinds = redact_secrets(text)
        assert out == text
        assert kinds == []

    def test_real_aws_key_still_masked(self):
        out, kinds = redact_secrets("AKIA1234567890ABCDEF")
        assert out == f"AKIA{REDACTION_MARKER}"
        assert kinds == ["aws-access-key"]

    def test_already_masked_text_is_a_noop(self):
        text = f"apiKey: AIza{REDACTION_MARKER},"
        out, kinds = redact_secrets(text)
        assert out == text
        assert kinds == []

    def test_empty_text(self):
        assert redact_secrets("") == ("", [])
