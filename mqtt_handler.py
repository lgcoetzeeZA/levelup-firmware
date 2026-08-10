import time
import ujson
from umqtt.simple import MQTTClient

RECONNECT_MIN_INTERVAL = 5  # seconds between reconnect attempts - avoids hammering the broker
SOCKET_TIMEOUT_SEC = 5

# Note: this firmware's built-in socket module doesn't support
# setdefaulttimeout() or monkey-patching socket.socket - it's a native
# module that only allows reading existing attributes, not reassigning
# them. So the very first connect() call (before we have a socket object
# to call settimeout() on) can't be bounded this way. If that specific
# call ever hangs, the watchdog is the safety net that recovers it - we've
# confirmed it does so cleanly. Every subsequent socket call, once
# connected, IS protected below via client.sock.settimeout().


class MQTTHandler:
    def __init__(self, client_id, server, sub_topic=None, on_message=None, keepalive=60,
                 lw_topic=None, lw_msg=None):
        self.client_id = client_id
        self.server = server
        self.sub_topic = sub_topic
        self.on_message = on_message
        self.keepalive = keepalive
        self.lw_topic = lw_topic  # e.g. "<clientId>/LevelUp/status"
        self.lw_msg = lw_msg      # e.g. "offline" - broker auto-publishes this
                                   # (retained) if the connection drops ungracefully

        self.client = None
        self.connected = False
        self._last_ping = 0
        self._last_connect_attempt = 0

    def _try_connect(self):
        try:
            client = MQTTClient(self.client_id, self.server, keepalive=self.keepalive)
            if self.on_message:
                client.set_callback(self.on_message)
            if self.lw_topic and self.lw_msg:
                client.set_last_will(self.lw_topic, self.lw_msg, retain=True, qos=0)
            client.connect()
            if self.sub_topic:
                client.subscribe(self.sub_topic)
            try:
                # Without this, a stalled connection can leave a socket call
                # blocking indefinitely - which starves the main task and
                # can trip the ESP-IDF's own task watchdog, not just ours.
                client.sock.settimeout(5)
            except (AttributeError, OSError) as e:
                print("Could not set MQTT socket timeout:", e)
            self.client = client
            self.connected = True
            self._last_ping = time.time()
            print("MQTT connected to", self.server)

            if self.lw_topic:
                # The Last Will only fires on an *ungraceful* disconnect -
                # we still need to proactively announce "online" ourselves
                # on every successful (re)connect.
                try:
                    client.publish(self.lw_topic, "online", retain=True)
                except OSError as e:
                    print("Could not publish online status:", e)

            return True
        except OSError as e:
            print("MQTT connect failed:", e)
            self.connected = False
            return False

    def ensure_connected(self):
        """Call once per main loop iteration. Never blocks: if not connected,
        tries at most once every RECONNECT_MIN_INTERVAL seconds. Returns the
        current connection state."""
        if self.connected:
            return True

        now = time.time()
        if now - self._last_connect_attempt < RECONNECT_MIN_INTERVAL:
            return False

        self._last_connect_attempt = now
        return self._try_connect()

    def check_messages(self):
        """Non-blocking check for incoming messages (e.g. relay commands).
        Call once per main loop iteration."""
        if not self.connected or self.client is None:
            return
        try:
            self.client.check_msg()
        except OSError as e:
            print("MQTT check_msg failed:", e)
            self.connected = False

    def keepalive_ping(self):
        """Sends a PING if roughly half the keepalive interval has passed.
        Call once per main loop iteration; it self-throttles."""
        if not self.connected or self.client is None:
            return
        now = time.time()
        if now - self._last_ping >= (self.keepalive // 2):
            try:
                self.client.ping()
                self._last_ping = now
            except OSError as e:
                print("MQTT ping failed:", e)
                self.connected = False

    def publish_json(self, topic, data):
        """Publish a dict as a JSON payload. Returns True on success, False
        on failure (and marks the connection as needing reconnect rather
        than raising)."""
        if not self.connected or self.client is None:
            return False
        try:
            self.client.publish(topic, ujson.dumps(data))
            return True
        except OSError as e:
            print("MQTT publish failed:", e)
            self.connected = False
            return False

    def publish_raw(self, topic, payload, retain=False):
        """Publish a raw string/bytes payload (no JSON wrapping) - useful
        for dashboard widgets that expect plain text like 'relayOn'."""
        if not self.connected or self.client is None:
            return False
        try:
            self.client.publish(topic, payload, retain=retain)
            return True
        except OSError as e:
            print("MQTT publish failed:", e)
            self.connected = False
            return False
