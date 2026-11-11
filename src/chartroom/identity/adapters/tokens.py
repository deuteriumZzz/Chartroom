from datetime import UTC, datetime, timedelta

import jwt

from chartroom.identity.domain import InvalidTokenError


class JwtTokenService:
    """HS256 JWT. В токене только id пользователя: роль читается из БД на каждый запрос."""

    _ALGORITHM = "HS256"

    def __init__(self, secret: str, ttl: timedelta) -> None:
        self._secret = secret
        self._ttl = ttl

    def issue(self, user_id: int) -> str:
        now = datetime.now(UTC)
        payload = {"sub": str(user_id), "iat": now, "exp": now + self._ttl}
        return jwt.encode(payload, self._secret, algorithm=self._ALGORITHM)

    def read_user_id(self, token: str) -> int:
        try:
            # Явный список алгоритмов закрывает подмену alg, в том числе "none".
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._ALGORITHM],
                options={"require": ["exp", "sub"]},
            )
            return int(payload["sub"])
        except (jwt.InvalidTokenError, ValueError) as e:
            raise InvalidTokenError from e
