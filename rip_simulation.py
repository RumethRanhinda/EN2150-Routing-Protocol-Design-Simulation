import heapq
import random
import copy
import ipaddress
from collections import deque

# ==========================================
# 1. DISCRETE EVENT SIMULATOR ENGINE
# ==========================================
class Event:
    def __init__(self, time, callback, description=""):
        self.time = time
        self.callback = callback
        self.description = description
    
    def __lt__(self, other):
        return self.time < other.time

class Simulator:
    """A research-grade Discrete Event Simulator for precise timing and metrics."""
    def __init__(self):
        self.clock = 0.0
        self.events = []
        self.metrics = {
            'total_packets_sent': 0,
            'routing_table_updates': 0,
            'convergence_time_sec': 0.0,
            'dropped_packets_congestion': 0
        }
        self._is_converged = False
        self._last_change_time = 0.0

    def schedule(self, delay, callback, description=""):
        heapq.heappush(self.events, Event(self.clock + delay, callback, description))

    def run(self, max_time=1000):
        while self.events and self.clock <= max_time:
            event = heapq.heappop(self.events)
            self.clock = event.time
            self.check_convergence()
            event.callback()
            
        # If the event queue completely empties out (like in purely event-driven RIP-C),
        # the network is by definition perfectly converged.
        if not self._is_converged and self._last_change_time > 0:
            self._is_converged = True
            self.metrics['convergence_time_sec'] = self._last_change_time

    def record_change(self):
        self.metrics['routing_table_updates'] += 1
        self._last_change_time = self.clock
        self._is_converged = False

    def record_packet(self):
        self.metrics['total_packets_sent'] += 1

    def record_drop(self):
        self.metrics['dropped_packets_congestion'] += 1

    def check_convergence(self):
        if not self._is_converged and self._last_change_time > 0 and (self.clock - self._last_change_time > 250):
            self._is_converged = True
            self.metrics['convergence_time_sec'] = self._last_change_time

# ==========================================
# 2. NETWORK ELEMENTS
# ==========================================
class Link:
    def __init__(self, node1, node2, delay=0.01, bandwidth_bps=10_000_000):
        self.node1 = node1
        self.node2 = node2
        self.delay = delay               
        self.bandwidth_bps = bandwidth_bps 
        self.active = True               

    def transmit(self, packet, source_router, sim):
        if not self.active: return
        
        sim.record_packet()
        dest_router = self.node2 if source_router == self.node1 else self.node1
        
        # 512 bytes max per RIP udp packet -> 4096 bits
        packet_size_bits = 4096 
        transmission_delay = packet_size_bits / self.bandwidth_bps
        total_delay = transmission_delay + self.delay
        
        pkt_copy = copy.deepcopy(packet)
        # Packet arrives at the destination router's hardware queue
        sim.schedule(total_delay, lambda: dest_router.enqueue_packet(pkt_copy, source_router.node_id))

class Router:
    """Hardware abstraction with dynamic max queue depth."""
    def __init__(self, node_id, sim, protocol_class, process_delay=0.01, max_queue_depth=50):
        self.node_id = node_id
        self.sim = sim
        self.links = []
        self.process_delay = process_delay               
        self.max_queue_depth = max_queue_depth 
        self.queue = deque()
        self.is_processing = False
        
        self.protocol = protocol_class(self, sim)

    def add_link(self, link):
        self.links.append(link)

    def get_neighbor_id(self, link):
        return link.node2.node_id if link.node1 == self else link.node1.node_id

    def enqueue_packet(self, packet, sender_id):
        if len(self.queue) >= self.max_queue_depth:
            self.sim.record_drop()
            return
        
        self.queue.append((packet, sender_id))
        if not self.is_processing:
            self._process_next()

    def _process_next(self):
        if not self.queue:
            self.is_processing = False
            return
        self.is_processing = True
        packet, sender_id = self.queue.popleft()
        # Simulate time taken by CPU to process packet
        self.sim.schedule(self.process_delay, lambda: self._handle_packet(packet, sender_id))

    def _handle_packet(self, packet, sender_id):
        self.protocol.receive_packet(packet, sender_id)
        # Immediately start processing next packet in queue
        self.sim.schedule(0, self._process_next)

    def send_to(self, packet, neighbor_id):
        for link in self.links:
            if self.get_neighbor_id(link) == neighbor_id:
                link.transmit(packet, self, self.sim)
                break

# ==========================================
# 3. ROUTING PROTOCOLS
# ==========================================
class RouteEntry:
    def __init__(self, network, metric, sim_time, route_tag=0, seq_num=0, bw=0, lat=0):
        self.network = network          
        self.next_hops = {}             # ECMP Dictionary mapping: {neighbor_id: last_updated_time}
        self.metric = metric
        self.route_tag = route_tag      # External Route Tag identifier
        self.garbage_timer_start = None
        # RIP-C specific variables
        self.sequence_number = seq_num
        self.bottleneck_bandwidth = bw
        self.cumulative_latency = lat

class StandardRIPv2:
    """Fully compliant RIPv2 Protocol (RFC 2453)"""
    INFINITY = 16
    UPDATE_INTERVAL = 30
    INVALID_TIMER = 180
    GARBAGE_COLLECTION_TIMER = 120
    AUTH_KEY = "secret_key" # RIPv2 Plaintext Authentication string

    def __init__(self, router, sim):
        self.router = router
        self.sim = sim
        self.table = {} 
        self._pending_triggered_update = False # Rate Limiter Flag
        
        # 1. Initialization Request on boot
        self.sim.schedule(random.uniform(0.1, 1.0), self.send_initialization_request)
        # 2. Start Periodic updates
        self.sim.schedule(random.uniform(1.0, 5.0), self.send_periodic_update)
        # 3. Check timers every second
        self.sim.schedule(1, self.check_timers)

    def add_local_network(self, network_str, route_tag=0):
        net = ipaddress.IPv4Network(network_str)
        entry = RouteEntry(net, 1, self.sim.clock, route_tag=route_tag)
        entry.next_hops[self.router.node_id] = self.sim.clock # Self is permanently updated
        self.table[net] = entry
        self.sim.record_change()

    def send_initialization_request(self):
        """Broadcasts a full routing table request upon startup using AFI 0."""
        packet = {
            'command': 1, 
            'version': 2,
            'entries': [{'afi': 0, 'route_tag': 0, 'network': '0.0.0.0/0', 'metric': 16}], 
            'sender': self.router.node_id
        }
        for link in self.router.links:
            if link.active:
                self.router.send_to(packet, self.router.get_neighbor_id(link))

    def send_periodic_update(self):
        self._broadcast_table()
        jitter = random.uniform(-self.UPDATE_INTERVAL * 0.15, self.UPDATE_INTERVAL * 0.15)
        self.sim.schedule(self.UPDATE_INTERVAL + jitter, self.send_periodic_update)

    def _broadcast_table(self, triggered=False, target_neighbor=None):
        for link in self.router.links:
            if not link.active: continue
            neighbor_id = self.router.get_neighbor_id(link)
            
            if target_neighbor and neighbor_id != target_neighbor:
                continue

            entries = []
            for net, entry in self.table.items():
                metric = entry.metric
                
                # Split Horizon with Poison Reverse
                # If we learned the route EXCLUSIVELY from this neighbor, we must advertise it as unreachable
                if neighbor_id in entry.next_hops and len(entry.next_hops) == 1:
                    metric = self.INFINITY
                    
                entries.append({
                    'afi': 2, 
                    'route_tag': entry.route_tag,
                    'network': str(net), 
                    'metric': metric
                })
            
            if not entries:
                continue
                
            # 25-Route Packet Limit & Fragmentation
            # RIPv2 Auth consumes the first entry, leaving 24 entries max per packet payload.
            max_entries_per_packet = 24
            
            for i in range(0, len(entries), max_entries_per_packet):
                chunk = entries[i:i+max_entries_per_packet]
                
                # Prepend RIPv2 Authentication Header (AFI 0xFFFF)
                chunk.insert(0, {
                    'afi': 0xFFFF,
                    'auth_type': 2, # Plaintext
                    'auth_data': self.AUTH_KEY
                })
                
                packet = {
                    'command': 2, 
                    'version': 2,
                    'entries': chunk, 
                    'sender': self.router.node_id
                }
                self.router.send_to(packet, neighbor_id)

    def receive_packet(self, packet, sender_id):
        if packet['command'] == 1: # Received a Request
            # Check for Full Table Request Granularity
            if len(packet['entries']) == 1 and packet['entries'][0]['afi'] == 0 and packet['entries'][0]['metric'] == 16:
                self._broadcast_table(target_neighbor=sender_id)
            else:
                # Specific Route Request handling
                response_entries = []
                for req in packet['entries']:
                    if req['afi'] != 2: continue
                    net = ipaddress.IPv4Network(req['network'])
                    metric = self.INFINITY
                    if net in self.table:
                        metric = self.table[net].metric
                    response_entries.append({
                        'afi': 2, 'route_tag': req['route_tag'], 'network': str(net), 'metric': metric
                    })
                if response_entries:
                    self.router.send_to({'command': 2, 'version': 2, 'entries': response_entries, 'sender': self.router.node_id}, sender_id)
                    
        elif packet['command'] == 2: # Received an Update Response
            self._handle_response(packet, sender_id)

    def _handle_response(self, packet, sender_id):
        changed = False
        entries = packet['entries']
        
        if not entries: return
        
        # 1. Check Authentication Header
        if entries[0]['afi'] == 0xFFFF:
            if entries[0].get('auth_data') != self.AUTH_KEY:
                return # Authentication Failed: Drop Packet silently
            entries = entries[1:] # Strip Auth Header before processing routing data
            
        for entry_data in entries:
            if entry_data['afi'] != 2: continue # Ignore unsupported AFIs
            
            net = ipaddress.IPv4Network(entry_data['network'])
            new_metric = min(entry_data['metric'] + 1, self.INFINITY)
            route_tag = entry_data.get('route_tag', 0)

            if net not in self.table:
                if new_metric < self.INFINITY:
                    entry = RouteEntry(net, new_metric, self.sim.clock, route_tag=route_tag)
                    entry.next_hops[sender_id] = self.sim.clock
                    self.table[net] = entry
                    changed = True
            else:
                current = self.table[net]
                
                if new_metric == current.metric and new_metric < self.INFINITY:
                    # ECMP: Add or Update neighbor in Equal Cost Multi-Path dictionary
                    if sender_id not in current.next_hops:
                        changed = True # New topology path discovered
                    current.next_hops[sender_id] = self.sim.clock
                    
                elif new_metric < current.metric:
                    # Strictly better path found
                    current.metric = new_metric
                    current.next_hops = {sender_id: self.sim.clock}
                    current.route_tag = route_tag
                    current.garbage_timer_start = None
                    changed = True
                    
                elif sender_id in current.next_hops:
                    # Update from an existing next_hop
                    if new_metric != current.metric:
                        if len(current.next_hops) == 1:
                            # Our only path got worse
                            current.metric = new_metric
                            current.next_hops[sender_id] = self.sim.clock
                            changed = True
                            if new_metric == self.INFINITY and current.garbage_timer_start is None:
                                current.garbage_timer_start = self.sim.clock
                        else:
                            # One of our ECMP paths got worse, safely drop it to avoid blackholing
                            del current.next_hops[sender_id]
                            changed = True
                    else:
                        # Metric unchanged, safely refresh just this neighbor's timer
                        current.next_hops[sender_id] = self.sim.clock

        if changed:
            self.sim.record_change()
            self.on_table_change()

    def on_table_change(self):
        """Rate Limited Triggered Updates (RFC 2453 batching)"""
        if not self._pending_triggered_update:
            self._pending_triggered_update = True
            delay = random.uniform(1.0, 5.0) 
            self.sim.schedule(delay, self._execute_triggered_update)

    def _execute_triggered_update(self):
        if self._pending_triggered_update:
            self._broadcast_table(triggered=True)
            self._pending_triggered_update = False

    def check_timers(self):
        to_delete = []
        changed = False
        for net, entry in list(self.table.items()):
            if self.router.node_id in entry.next_hops: continue # Don't age out local networks
            
            # 1. Individually age out ECMP neighbors
            expired_neighbors = []
            for neighbor_id, last_updated in entry.next_hops.items():
                if (self.sim.clock - last_updated) >= self.INVALID_TIMER:
                    expired_neighbors.append(neighbor_id)
                    
            for neighbor_id in expired_neighbors:
                del entry.next_hops[neighbor_id]
                changed = True
                
            # 2. If all neighbors expired, poison the route
            if len(entry.next_hops) == 0 and entry.metric < self.INFINITY:
                entry.metric = self.INFINITY
                entry.garbage_timer_start = self.sim.clock
                changed = True
            
            # 3. Garbage Collection Timer Expires (120s from poisoning)
            if entry.garbage_timer_start is not None:
                gb_age = self.sim.clock - entry.garbage_timer_start
                if gb_age >= self.GARBAGE_COLLECTION_TIMER:
                    to_delete.append(net)
        
        for net in to_delete:
            del self.table[net]
            changed = True

        if changed:
            self.sim.record_change()
            self.on_table_change()

        self.sim.schedule(1, self.check_timers)

    def route_lookup(self, ip_str):
        """Implements Longest Prefix Match (Subnetting / VLSM logic)."""
        ip = ipaddress.IPv4Address(ip_str)
        best_match = None
        longest_prefix = -1
        
        for net, entry in self.table.items():
            if ip in net and net.prefixlen > longest_prefix and entry.metric < self.INFINITY:
                best_match = entry
                longest_prefix = net.prefixlen
        return best_match



class RIP_C(StandardRIPv2):
    """Routing Information Protocol - Composite (RIP-C)
       Event-driven, Composite Metric, Sequence-based Loop Prevention"""
    INFINITY = 1_000_000

    def __init__(self, router, sim, K1=1, K2=1):
        super().__init__(router, sim)
        self.K1 = K1
        self.K2 = K2
        self.local_sequence_numbers = {} # Tracks sequence numbers for locally owned networks

    def send_periodic_update(self):
        # RIP-C abandons periodic updates. Only triggered updates.
        pass

    def check_timers(self):
        # RIP-C removes hold-down timers completely because sequence numbers prevent loops.
        pass

    def on_table_change(self):
        # Instant flash update at line-rate, completely overriding the inherited random delay
        self._broadcast_table(triggered=True)

    def add_local_network(self, network_str, route_tag=0):
        net = ipaddress.IPv4Network(network_str)
        self.local_sequence_numbers[net] = 1 # Start at sequence 1
        # Loopback bandwidth = 100 Gbps (100_000_000_000 bps), Latency = 0
        entry = RouteEntry(net, metric=0, sim_time=self.sim.clock, route_tag=route_tag, seq_num=1, bw=100_000_000_000, lat=0)
        entry.next_hops[self.router.node_id] = self.sim.clock 
        self.table[net] = entry
        self.sim.record_change()

    def send_initialization_request(self):
        # Broadcasts a full routing table request upon startup
        packet = {
            'command': 1, 
            'version': 2,
            'entries': [{'afi': 0, 'route_tag': 0, 'network': '0.0.0.0/0', 'metric': self.INFINITY, 'sequence_number': 0, 'bottleneck_bandwidth': 0, 'cumulative_latency': 0}], 
            'sender': self.router.node_id
        }
        for link in self.router.links:
            if link.active:
                self.router.send_to(packet, self.router.get_neighbor_id(link))

    def receive_packet(self, packet, sender_id):
        if packet['command'] == 1: 
            # Handle Cold Start Initialization Request
            if len(packet['entries']) == 1 and packet['entries'][0]['afi'] == 0 and packet['entries'][0]['metric'] == self.INFINITY:
                self._broadcast_table(target_neighbor=sender_id)
            else:
                response_entries = []
                for req in packet['entries']:
                    if req['afi'] != 2: continue
                    net = ipaddress.IPv4Network(req['network'])
                    metric = self.INFINITY
                    seq_num, bw, lat = 0, 0, 0
                    if net in self.table:
                        metric = self.table[net].metric
                        seq_num = self.table[net].sequence_number
                        bw = self.table[net].bottleneck_bandwidth
                        lat = self.table[net].cumulative_latency
                    response_entries.append({
                        'afi': 2, 'route_tag': req['route_tag'], 'network': str(net), 'metric': metric,
                        'sequence_number': seq_num, 'bottleneck_bandwidth': bw, 'cumulative_latency': lat
                    })
                if response_entries:
                    self.router.send_to({'command': 2, 'version': 2, 'entries': response_entries, 'sender': self.router.node_id}, sender_id)
                    
        elif packet['command'] == 2: 
            self._handle_response(packet, sender_id)

    def _broadcast_table(self, target_neighbor=None, triggered=False):
        entries = [{'afi': 0xFFFF, 'auth_data': self.AUTH_KEY}]
        
        for net, entry in self.table.items():
            entries.append({
                'afi': 2,
                'route_tag': entry.route_tag,
                'network': str(net),
                'metric': entry.metric,
                'sequence_number': entry.sequence_number,
                'bottleneck_bandwidth': entry.bottleneck_bandwidth,
                'cumulative_latency': entry.cumulative_latency
            })
            
            if len(entries) == 25:
                packet = {'command': 2, 'version': 2, 'entries': entries, 'sender': self.router.node_id}
                if target_neighbor: self.router.send_to(packet, target_neighbor)
                else:
                    for link in self.router.links:
                        if link.active: self.router.send_to(packet, self.router.get_neighbor_id(link))
                entries = [{'afi': 0xFFFF, 'auth_data': self.AUTH_KEY}]
                
        if len(entries) > 1:
            packet = {'command': 2, 'version': 2, 'entries': entries, 'sender': self.router.node_id}
            if target_neighbor: self.router.send_to(packet, target_neighbor)
            else:
                for link in self.router.links:
                    if link.active: self.router.send_to(packet, self.router.get_neighbor_id(link))

    def _handle_response(self, packet, sender_id):
        changed = False
        entries = packet['entries']
        
        if not entries: return
        if entries[0]['afi'] == 0xFFFF:
            if entries[0].get('auth_data') != self.AUTH_KEY: return 
            entries = entries[1:] 
            
        try:
            incoming_link = next(l for l in self.router.links if self.router.get_neighbor_id(l) == sender_id)
            link_lat = int(incoming_link.delay * 1_000_000) # seconds to microseconds
            link_bw = incoming_link.bandwidth_bps
        except StopIteration:
            return
            
        for entry_data in entries:
            if entry_data['afi'] != 2: continue 
            
            net = ipaddress.IPv4Network(entry_data['network'])
            adv_seq = entry_data['sequence_number']
            adv_bw = entry_data['bottleneck_bandwidth']
            adv_lat = entry_data['cumulative_latency']
            
            if net in self.local_sequence_numbers:
                if adv_seq > self.local_sequence_numbers[net] or (adv_seq == self.local_sequence_numbers[net] and entry_data['metric'] >= self.INFINITY):
                    new_seq = adv_seq + 1
                    self.local_sequence_numbers[net] = new_seq
                    self.table[net].sequence_number = new_seq
                    self.table[net].metric = 0 # Re-assert our metric is 0
                    changed = True
                continue # We never route to our own directly connected networks through others
            
            # Step 1: Update variables
            local_lat = adv_lat + link_lat
            local_bw = min(adv_bw, link_bw) if adv_bw > 0 else link_bw
            
            # Step 2: Calculate composite metric
            if entry_data['metric'] == self.INFINITY:
                new_cost = self.INFINITY
            else:
                local_bw_mbps = local_bw / 1_000_000
                if local_bw_mbps < 0.0001: local_bw_mbps = 0.0001
                new_cost = int(self.K1 * (100_000 / local_bw_mbps) + (self.K2 * local_lat))
                new_cost = min(new_cost, self.INFINITY)
                
            route_tag = entry_data.get('route_tag', 0)

            # Step 3: Evaluate against Routing Table
            if net not in self.table:
                if new_cost < self.INFINITY:
                    entry = RouteEntry(net, new_cost, self.sim.clock, route_tag=route_tag, seq_num=adv_seq, bw=local_bw, lat=local_lat)
                    entry.next_hops[sender_id] = self.sim.clock
                    self.table[net] = entry
                    changed = True
            else:
                current = self.table[net]
                current_seq = current.sequence_number
                
                # Wraparound logic
                diff = adv_seq - current_seq
                is_fresh = diff > 0 or (diff < 0 and abs(diff) > 2**31)
                
                if is_fresh:
                    # Rule 1: Freshness (Strict Sequence Override)
                    current.metric = new_cost
                    if new_cost < self.INFINITY:
                        current.next_hops = {sender_id: self.sim.clock}
                    else:
                        current.next_hops = {}
                    current.sequence_number = adv_seq
                    current.bottleneck_bandwidth = local_bw
                    current.cumulative_latency = local_lat
                    changed = True
                elif adv_seq == current_seq:
                    # Rule 2: Optimization (Metric Tie-Breaker)
                    if new_cost < current.metric:
                        current.metric = new_cost
                        current.next_hops = {sender_id: self.sim.clock}
                        current.bottleneck_bandwidth = local_bw
                        current.cumulative_latency = local_lat
                        changed = True
                    elif new_cost == current.metric and new_cost < self.INFINITY:
                        if sender_id not in current.next_hops: changed = True 
                        current.next_hops[sender_id] = self.sim.clock

        if changed:
            self.sim.record_change()
            self.on_table_change()

    def on_link_failure(self, failed_link):
        """Proxy Invalidation: Exceptionally increment sequence and poison route."""
        changed = False
        neighbor_id = self.router.get_neighbor_id(failed_link)
        
        for net, entry in self.table.items():
            if neighbor_id in entry.next_hops:
                del entry.next_hops[neighbor_id]
                if not entry.next_hops:
                    entry.metric = self.INFINITY
                    # Proxy invalidate: increment sequence by 1 to force neighbors to drop
                    entry.sequence_number += 1
                    changed = True
                    
        if changed:
            self.sim.record_change()
            self.on_table_change()

# ==========================================
# 4. EXPERIMENT RUNNER
# ==========================================
def build_mesh_topology(sim, protocol_class):
    

    nodes = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8',]
    routers = {n: Router(n, sim, protocol_class, process_delay=0.01, max_queue_depth=50) for n in nodes}
    
    links = [
        # Give links different delays (microseconds) and bandwidths to test RIP-C composite metric
        # Let's say latency parameter in Link is in seconds, so 0.01s = 10,000us
        Link(routers['R1'], routers['R2'], delay=0.002, bandwidth_bps=1_000_000_000), # 2ms, 1 Gbps
        Link(routers['R3'], routers['R4'], delay=0.005, bandwidth_bps=100_000_000),   # 5ms, 100 Mbps
        Link(routers['R1'], routers['R3'], delay=0.050, bandwidth_bps=10_000_000),    # 50ms, 10 Mbps
        Link(routers['R2'], routers['R4'], delay=0.020, bandwidth_bps=50_000_000),    # 20ms, 50 Mbps
        # Diagonal links for ECMP testing
        Link(routers['R1'], routers['R4'], delay=0.100, bandwidth_bps=5_000_000),     # 100ms, 5 Mbps
        Link(routers['R2'], routers['R3'], delay=0.010, bandwidth_bps=1_000_000_000)  # 10ms, 1 Gbps
    ]
    
    for l in links:
        l.node1.add_link(l)
        l.node2.add_link(l)
        
    routers['R1'].protocol.add_local_network("10.1.0.0/24")
    routers['R4'].protocol.add_local_network("10.4.0.0/24")
    routers['R4'].protocol.add_local_network("192.168.1.0/24")
    
    return routers, links


def build_test_topology(sim, protocol_class):

    nodes = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    routers = {n: Router(n, sim, protocol_class, process_delay=0.02, max_queue_depth=50) for n in nodes}

    links = [
        # --- THE HIGH-SPEED CORE (Longer hops, but blazing fast) ---
        Link(routers['A'], routers['B'], delay=0.001, bandwidth_bps=10_000_000_000), # 1ms, 10 Gbps
        Link(routers['B'], routers['C'], delay=0.001, bandwidth_bps=10_000_000_000), # 1ms, 10 Gbps
        Link(routers['C'], routers['D'], delay=0.001, bandwidth_bps=10_000_000_000), # 1ms, 10 Gbps
        Link(routers['D'], routers['G'], delay=0.001, bandwidth_bps=10_000_000_000), # 1ms, 10 Gbps

        # --- The Direct Link (1 hop, but terrible latency and bandwidth) ---
        Link(routers['A'], routers['C'], delay=0.100, bandwidth_bps=10_000_000),     # 100ms, 10 Mbps
        
        # --- The Shortcut (2 hops, but congested) ---
        Link(routers['A'], routers['F'], delay=0.050, bandwidth_bps=50_000_000),     # 50ms, 50 Mbps
        Link(routers['F'], routers['G'], delay=0.050, bandwidth_bps=50_000_000),     # 50ms, 50 Mbps

        # --- THE BRANCH (Standard connection) ---
        Link(routers['A'], routers['E'], delay=0.005, bandwidth_bps=1_000_000_000),  # 5ms, 1 Gbps
        Link(routers['E'], routers['H'], delay=0.005, bandwidth_bps=1_000_000_000)   # 5ms, 1 Gbps
    ]

    for l in links:
        l.node1.add_link(l)
        l.node2.add_link(l)
    
    # Assigning Local Networks
    routers['A'].protocol.add_local_network("10.1.0.0/24")
    routers['H'].protocol.add_local_network("10.2.0.0/24")
    routers['C'].protocol.add_local_network("10.3.0.0/24")
    routers['G'].protocol.add_local_network("10.4.0.0/24")

    return routers, links

def calculate_network_performance(routers):
    """Dynamically traces routing tables to calculate true path latency and bottleneck bandwidth."""
    total_latency_us = 0
    total_bandwidth_mbps = 0
    total_paths = 0

    for src_name, src_router in routers.items():
        for net in src_router.protocol.table.keys():
            current_router = src_router
            visited = set()
            path_latency = 0
            path_bw = float('inf')
            
            while True:
                if current_router.node_id in visited:
                    break # Routing loop detected
                visited.add(current_router.node_id)
                
                entry = current_router.protocol.table.get(net)
                if not entry or entry.metric >= current_router.protocol.INFINITY:
                    break # Destination unreachable
                    
                # If we've reached the router that owns the network
                if not entry.next_hops or current_router.node_id in entry.next_hops:
                    if path_bw != float('inf'): # Ignore if it was local to start with
                        total_latency_us += path_latency
                        total_bandwidth_mbps += (path_bw / 1_000_000)
                        total_paths += 1
                    break
                    
                # Follow the first next hop
                next_hop_id = next(iter(entry.next_hops.keys()))
                
                link_used = None
                for l in current_router.links:
                    if current_router.get_neighbor_id(l) == next_hop_id:
                        link_used = l
                        break
                        
                if not link_used:
                    break
                    
                path_latency += (link_used.delay * 1_000_000)
                path_bw = min(path_bw, link_used.bandwidth_bps)
                current_router = routers[next_hop_id]

    if total_paths > 0:
        avg_lat_ms = (total_latency_us / total_paths) / 1000.0
        avg_bw_mbps = total_bandwidth_mbps / total_paths
        return avg_lat_ms, avg_bw_mbps, total_paths
    return 0.0, 0.0, 0


def run_test(protocol_class=RIP_C):
    sim = Simulator()
    routers, links = build_test_topology(sim, protocol_class)

    # Run the simulation until convergence
    sim.run(max_time=1500)

    print(f"--results for {protocol_class.__name__} --")
    print(f"Total Packets Sent  : {sim.metrics['total_packets_sent']}")
    print(f"Routing Updates     : {sim.metrics['routing_table_updates']}")
    print(f"Convergence Time    : {sim.metrics['convergence_time_sec']:.2f} s")
    
    avg_lat, avg_bw, paths = calculate_network_performance(routers)
    print(f"Average Latency     : {avg_lat:.2f} ms")
    print(f"Average Bandwidth   : {avg_bw:.2f} Mbps")
    print(f"Total Active Paths  : {paths}\n")


def run_dynamic_test(protocol_class=RIP_C):
    sim = Simulator()
    routers, links = build_test_topology(sim, protocol_class)

    print(f"\n=======================================================")
    print(f"  Dynamic Failure Simulation: {protocol_class.__name__}")
    print(f"=======================================================")

    # Helper function to find a specific link safely
    def get_link(node1, node2):
        return next(l for l in links if 
                    (l.node1.node_id == node1 and l.node2.node_id == node2) or 
                    (l.node1.node_id == node2 and l.node2.node_id == node1))

    # Helper function to physically cut the cable and trigger protocols
    def trigger_link_failure(link):
        link.active = False
        # If the protocol is RIP-C, trigger its Proxy Invalidation exception
        if hasattr(link.node1.protocol, 'on_link_failure'):
            link.node1.protocol.on_link_failure(link)
        if hasattr(link.node2.protocol, 'on_link_failure'):
            link.node2.protocol.on_link_failure(link)
        sim.record_change()

    # --- PHASE 1: Initial Boot Convergence ---
    sim.run(max_time=300.0)
    print(f"[Phase 1] Initial Boot Convergence Time : {sim.metrics['convergence_time_sec']:.3f} s")

    # --- PHASE 2: Core Link Reroute ---
    print("\n--> [300.0s] EVENT: Cutting High-Speed Core Link (A -> C)")
    if sim.clock < 300.0:
        sim.clock = 300.0 # Fast-forward clock for sleeping event-driven protocols
    trigger_link_failure(get_link('A', 'C'))
    
    sim._is_converged = False # Reset the convergence tracker
    sim.run(max_time=600.0)
    
    # Calculate exactly how long it took to reroute after the 300s mark
    reroute_time = sim.metrics['convergence_time_sec'] - 300.0
    print(f"[Phase 2] Recovery Convergence Time     : {reroute_time:.3f} s")

    # --- PHASE 3: Total Node Isolation ---
    print("\n--> [600.0s] EVENT: Cutting Branch Link (E -> H) [Isolating Node H]")
    if sim.clock < 600.0:
        sim.clock = 600.0 # Fast-forward clock for sleeping event-driven protocols
    trigger_link_failure(get_link('E', 'H'))
    
    sim._is_converged = False # Reset the convergence tracker
    sim.run(max_time=1500.0)
    
    iso_time = sim.metrics['convergence_time_sec'] - 600.0
    print(f"[Phase 3] Isolation Convergence Time    : {iso_time:.3f} s")

    # --- Final Network Telemetry ---
    print("\n--- Final Network Telemetry ---")
    print(f"Total Packets Sent  : {sim.metrics['total_packets_sent']}")
    print(f"Routing Updates     : {sim.metrics['routing_table_updates']}")
    
    avg_lat, avg_bw, paths = calculate_network_performance(routers)
    print(f"Average Latency     : {avg_lat:.2f} ms")
    print(f"Average Bandwidth   : {avg_bw:.2f} Mbps")
    print(f"Total Active Paths  : {paths}")
    
    # --- PROOF OF ISOLATION ---
    import ipaddress
    target_net = ipaddress.IPv4Network("10.2.0.0/24") # Node H's Network
    route_in_A = routers['A'].protocol.table.get(target_net)
    
    print("\n--- Route Verification (Looking at Router A) ---")
    if not route_in_A or route_in_A.metric >= routers['A'].protocol.INFINITY:
        print("Status of 10.2.0.0/24 (Node H) : PERFECTLY ISOLATED (Metric = Infinity)")
    else:
        print("Status of 10.2.0.0/24 (Node H) : WARNING - STILL REACHABLE (Ghost Route!)")
    print("=======================================================\n")



if __name__ == "__main__":
    # run_mesh2_experiment(protocol_class=StandardRIPv2)
    # run_mesh2_experiment(protocol_class=RIP_C)

    run_test(protocol_class=StandardRIPv2)
    run_test(protocol_class=RIP_C)

    run_dynamic_test(protocol_class=StandardRIPv2)
    run_dynamic_test(protocol_class=RIP_C)




