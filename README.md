# RIP-C and Standard RIPv2 Simulation

## Project Summary

This project introduces **Routing Information Protocol - Composite (RIP-C)**, an enhanced interior gateway protocol developed by Team Lattice. RIP-C is designed to overcome the primary limitations of legacy RIPv2, specifically its reliance on a simple hop-count metric and its slow convergence times.

**Key Architectural Enhancements:**
* **Composite Metric:** RIP-C replaces the standard hop-count with a normalized, bandwidth-and-latency-aware composite metric. This allows the protocol to intelligently differentiate between high-capacity fiber links and slower, congested connections.
* **Event-Driven Updates:** The architecture shifts from a timer-based broadcast model (sending updates every 30 seconds) to a purely event-driven framework using Triggered Updates. Routers only broadcast changes when a link state shifts, a sequence number increments, or a metric changes.
* **Destination Sequence Numbers:** By implementing authoritative Destination Sequence Numbers, RIP-C inherently eliminates routing loops and the "counting to infinity" vulnerability. This instantly invalidates stale paths and renders legacy hold-down timers obsolete.

*(📸 **Add an image/video here:** Consider adding a GIF or image of the `RIP-C Route Evaluation Flowchart` from the report to visually explain the algorithm.)*

---

## Simulation Results and Evaluation

The performance of RIP-C was evaluated against standard RIPv2 using a customized simulation network topology. The implementation of the composite metric and event-driven updates yielded significant performance enhancements.

### Initial Boot Convergence
During the initial network convergence phase, RIP-C dramatically outperformed standard RIPv2 across multiple metrics:
* **Convergence Time:** Achieved an **84.2% reduction** in convergence time, dropping from 5.02 seconds in RIPv2 to just 0.79 seconds.
* **Average Latency:** Optimized average path latency by **79.0%** (from 61.50 ms down to 12.86 ms).
* **Bottleneck Bandwidth:** Increased average bottleneck bandwidth by **101.0%** (from 2340.36 Mbps to 4721.43 Mbps).

*(📸 **Add an image here:** A screenshot of the terminal output showing the "Comparative Analysis of Initial Boot Convergence Metrics" would fit perfectly here.)*

### Dynamic Resilience (Link Failure)
A secondary experiment tested the network's resilience by simulating a physical failure on a high-speed core link (Node A to Node C). 
* **Legacy RIPv2:** Suffered a recovery convergence time of 182.307 seconds due to reliance on wait timers and "counting to infinity".
* **RIP-C:** Achieved instantaneous recovery with a **0.000 s convergence time**, instantly flushing stale paths from the network.

*(🎥 **Add a video here:** A short video recording of the simulation running the link-failure event side-by-side (RIPv2 vs. RIP-C) would perfectly demonstrate the real-time recovery speed.)*

### Known Trade-offs
While RIP-C optimizes speed and routing efficiency, it introduces a few structural trade-offs:
* **Payload Overhead:** The routing entry payload size increases by 60% (from 20 bytes to 32 bytes) to accommodate the new composite metric variables and sequence numbers.
* **Parameter Synchronization:** The protocol requires strict domain-wide synchronization of the metric weightings ($K_{1}$ and $K_{2}$); misconfigurations can result in asymmetric path costs and artificial loops.


This project implements a discrete-event simulator to evaluate and compare the Standard Routing Information Protocol (RIPv2) and an experimental Composite Metric Routing Protocol (RIP-C).


## Authors & Acknowledgments

* **Team Lattice** (Department of Electronic & Telecommunication Engineering, University of Moratuwa): *(From Left to Right)*  
  * Ilankoon I.M.M.K.B. - 230256U
  * Imaduwage O.N.H. - 230258D
  * Jayasinghe J.A.P.R. - 230280L
  * Samarasinghe S.M.R.R. - 230566U



---

## 1. Getting Started

### Prerequisites
The simulation is written in pure Python and only utilizes built-in libraries. You do not need to install any external dependencies (e.g., no `pip install` required).

The standard libraries used are:
- `heapq` (for the discrete event priority queue)
- `random` (for update jitter and timer variance)
- `copy` (for deep copying packet data)
- `ipaddress` (for CIDR/VLSM longest prefix matching)
- `collections.deque` (for router hardware queues)

### How to Run
To execute the predefined tests, simply run the python file from your terminal:
```bash
python rip_simulation.py
```
This will automatically execute the baseline tests and dynamic link failure tests comparing Standard RIPv2 against RIP-C, printing the convergence times, telemetry, and network latency/bandwidth metrics to the console.

## 2. Simulation Architecture

### The Discrete Event Simulator (`Simulator`)
The core of the project is a custom Discrete Event Simulator (DES). Unlike a continuous loop or thread-based simulation, a DES operates by scheduling events at specific virtual timestamps. Time instantly jumps to the timestamp of the next event in the priority queue (`heapq`). This allows for perfectly synchronized, deterministic testing of protocol convergence times without being affected by the host machine's CPU speed.

### Hardware Abstractions
- **`Link`**: Simulates a physical cable with a specific propagation delay and bandwidth capacity. It handles the serialization of packets and delays their arrival at the destination based on packet size and bandwidth.
- **`Router`**: Represents a physical routing node. It possesses a hardware packet queue (with max depth to simulate congestion drops) and processes packets sequentially using a specific processing delay to emulate CPU limitations.

### Protocol Definitions
Routing protocols are defined as classes that interface with the `Router` hardware.
- **`StandardRIPv2`**: Implements an RFC 2453 compliant distance-vector routing protocol. It features Split Horizon with Poison Reverse, periodic broadcast timers, batching for triggered updates, and standard garbage collection timers. It strictly uses hop count (Max 16) as a metric.
- **`RIP_C`**: An experimental composite metric modification that inherits from `StandardRIPv2`. It abandons periodic updates in favor of purely event-driven, instantaneous flash updates. It uses a DSDV-style sequence-number loop prevention system and calculates route metrics using a composite formula of bottleneck bandwidth and cumulative latency instead of hop-count.

## 3. Defining a Network Topology

To simulate a network, you must construct it programmatically within a topology builder function. A topology builder instantiates the routers, links them together, and assigns local subnetworks.

Here is an example of how to define a topology function:

```python
def build_custom_topology(sim, protocol_class):
    # 1. Instantiate Routers
    nodes = ['R1', 'R2', 'R3']
    routers = {n: Router(n, sim, protocol_class) for n in nodes}
    
    # 2. Define Links with delay (seconds) and bandwidth (bps)
    links = [
        Link(routers['R1'], routers['R2'], delay=0.01, bandwidth_bps=1_000_000),
        Link(routers['R2'], routers['R3'], delay=0.02, bandwidth_bps=5_000_000)
    ]
    
    # 3. Attach Links to Routers
    for l in links:
        l.node1.add_link(l)
        l.node2.add_link(l)
        
    # 4. Assign locally connected IP networks
    routers['R1'].protocol.add_local_network("10.1.0.0/24")
    routers['R3'].protocol.add_local_network("192.168.1.0/24")
    
    return routers, links
```

## 4. Writing a Test Runner

Once you have defined a topology, you create a test function to orchestrate the simulation, execute events (like link failures), and observe the results.

```python
def run_custom_test(protocol_class):
    # 1. Initialize the Simulator and build the topology
    sim = Simulator()
    routers, links = build_custom_topology(sim, protocol_class)
    
    # 2. Run initial convergence
    sim.run(max_time=300.0)
    print(f"Boot Convergence Time: {sim.metrics['convergence_time_sec']}s")
    
    # 3. Inject a dynamic failure
    print("Cutting link between R1 and R2...")
    link_to_cut = links[0]
    link_to_cut.active = False
    
    # Notify protocols of physical link layer failure (Proxy Invalidation)
    if hasattr(link_to_cut.node1.protocol, 'on_link_failure'):
        link_to_cut.node1.protocol.on_link_failure(link_to_cut)
    if hasattr(link_to_cut.node2.protocol, 'on_link_failure'):
        link_to_cut.node2.protocol.on_link_failure(link_to_cut)
        
    sim.record_change() # Log the topology change
    
    # 4. Fast-forward clock if necessary (for perfectly silent event-driven protocols)
    if sim.clock < 300.0:
        sim.clock = 300.0
        
    # 5. Run the simulator to calculate reroute/recovery time
    sim._is_converged = False 
    sim.run(max_time=600.0)
    reroute_time = sim.metrics['convergence_time_sec'] - 300.0
    print(f"Recovery Time: {reroute_time}s")
```

At the bottom of `rip_simulation.py`, simply invoke your test function with the desired protocol class:
```python
if __name__ == "__main__":
    run_custom_test(StandardRIPv2)
    run_custom_test(RIP_C)
```
