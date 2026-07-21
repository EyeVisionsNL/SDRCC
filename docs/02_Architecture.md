# Architecture

Core flow:

Mission Definitions
-> Mission Planner
-> Mission Scheduler
-> Resource Allocator
-> Mission Runtime(s)
-> Receiver Manager
-> SDR Hardware

Receiver Manager is the only component that controls physical SDR devices.
