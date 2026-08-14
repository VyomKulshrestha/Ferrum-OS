# Ferrum Physical Simulator Bridge

This host-side bridge connects Ferrum's versioned cyber-physical envelopes to a
physics backend. It does not grant physical authority and it does not run a motor
control loop.

Supported software boundaries:

- `ScriptedBackend` for deterministic tests and record/replay fixtures.
- `GazeboRos2Backend` for canonical JSON envelopes carried on ROS 2 topics.
- `WebotsBackend` for canonical envelopes carried by a Webots Receiver/Emitter.
- `ActuatorDisabledBackend` for hardware-in-the-loop sessions that must record but
  cannot energize an actuator.
- `BridgePump` as the transport-neutral canonical byte boundary for a vsock, TCP,
  or test-pipe host gateway. Delivery acknowledgements distinguish accepted,
  actuator-disabled, and uncertain states and never authorize blind retries.

The bridge rejects unknown fields, non-finite values, unsupported evidence classes,
run/epoch changes, source-clock changes, replayed observations, expired commands,
duplicate idempotency keys, and commands that lack Ferrum routed-command authority.

Run the dependency-free tests from the repository root:

```powershell
python -m unittest tools.physical_sim_bridge.test_bridge
```

Gazebo requires a ROS 2 Python environment with `rclpy` and `std_msgs`. The bridge
uses `/ferrum/observations` and `/ferrum/commands` by default. A Gazebo system/plugin
is responsible for translating its robot and sensor state into the registered JSON
payloads.

Webots requires its Python `controller` module and a world exposing Receiver
`ferrum_rx` and Emitter `ferrum_tx` devices.

These connectors complete the software contract and test boundary. They are not
evidence of a live Gazebo/Webots installation, physical hardware, real-time behavior,
or machinery-safety certification.
