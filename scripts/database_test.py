#!/usr/bin/env python3
"""
Azure SQL Performance Testing Script

Tests connection pooling, query performance, and concurrent operations
across all 4 databases (core, send, inventory, fulfillment).

Usage:
    # From project root
    python test_database_performance.py

    # Specific database only
    python test_database_performance.py --db core

    # With custom load
    python test_database_performance.py --connections 50 --queries 200
"""

import os
import sys
import time
import argparse
import threading
from datetime import datetime
from typing import List, Dict, Any
import statistics

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables (for local testing)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.core.database import (
    get_db_connection, 
    get_pool_metrics,
    cleanup_all_pools,
    DatabaseError
)


class PerformanceTest:
    """Performance testing for Azure SQL connections."""
    
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.results = {
            "connection_times": [],
            "query_times": [],
            "errors": [],
            "concurrent_success": 0,
            "concurrent_failures": 0
        }
    
    def test_connection(self) -> float:
        """Test a single connection and return time taken."""
        start = time.time()
        try:
            with get_db_connection(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
            duration = time.time() - start
            self.results["connection_times"].append(duration)
            return duration
        except Exception as e:
            self.results["errors"].append(str(e))
            return -1
    
    def test_simple_query(self) -> float:
        """Test a simple query and return time taken."""
        start = time.time()
        try:
            with get_db_connection(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        COUNT(*) as count,
                        GETDATE() as current_time,
                        @@VERSION as version
                """)
                result = cursor.fetchone()
                cursor.close()
            duration = time.time() - start
            self.results["query_times"].append(duration)
            return duration
        except Exception as e:
            self.results["errors"].append(str(e))
            return -1
    
    def test_concurrent_worker(self, num_queries: int):
        """Worker function for concurrent testing."""
        for _ in range(num_queries):
            try:
                with get_db_connection(self.db_name) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.close()
                self.results["concurrent_success"] += 1
            except Exception as e:
                self.results["concurrent_failures"] += 1
    
    def test_concurrent_load(self, num_threads: int = 10, queries_per_thread: int = 20):
        """Test concurrent database access."""
        threads = []
        start = time.time()
        
        for _ in range(num_threads):
            thread = threading.Thread(
                target=self.test_concurrent_worker,
                args=(queries_per_thread,)
            )
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        duration = time.time() - start
        total_queries = num_threads * queries_per_thread
        
        return {
            "duration": duration,
            "total_queries": total_queries,
            "queries_per_second": total_queries / duration if duration > 0 else 0,
            "success_rate": (
                self.results["concurrent_success"] / total_queries * 100 
                if total_queries > 0 else 0
            )
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get test results summary."""
        conn_times = [t for t in self.results["connection_times"] if t > 0]
        query_times = [t for t in self.results["query_times"] if t > 0]
        
        return {
            "database": self.db_name,
            "connections": {
                "total": len(self.results["connection_times"]),
                "successful": len(conn_times),
                "failed": len([t for t in self.results["connection_times"] if t < 0]),
                "avg_time_ms": statistics.mean(conn_times) * 1000 if conn_times else 0,
                "min_time_ms": min(conn_times) * 1000 if conn_times else 0,
                "max_time_ms": max(conn_times) * 1000 if conn_times else 0,
                "median_time_ms": statistics.median(conn_times) * 1000 if conn_times else 0,
            },
            "queries": {
                "total": len(self.results["query_times"]),
                "successful": len(query_times),
                "failed": len([t for t in self.results["query_times"] if t < 0]),
                "avg_time_ms": statistics.mean(query_times) * 1000 if query_times else 0,
                "min_time_ms": min(query_times) * 1000 if query_times else 0,
                "max_time_ms": max(query_times) * 1000 if query_times else 0,
                "median_time_ms": statistics.median(query_times) * 1000 if query_times else 0,
            },
            "errors": len(self.results["errors"]),
            "error_samples": self.results["errors"][:5] if self.results["errors"] else []
        }


def print_separator(char="=", length=80):
    """Print a separator line."""
    print(char * length)


def print_header(text: str):
    """Print a formatted header."""
    print_separator()
    print(f"  {text}")
    print_separator()


def run_database_tests(
    db_names: List[str],
    num_connections: int = 20,
    num_queries: int = 50,
    concurrent_threads: int = 10,
    queries_per_thread: int = 20
):
    """Run comprehensive performance tests."""
    
    print_header("AZURE SQL PERFORMANCE TEST")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Testing databases: {', '.join(db_names)}")
    print(f"Configuration:")
    print(f"  - Connection tests: {num_connections}")
    print(f"  - Query tests: {num_queries}")
    print(f"  - Concurrent threads: {concurrent_threads}")
    print(f"  - Queries per thread: {queries_per_thread}")
    print()
    
    all_results = {}
    
    for db_name in db_names:
        print_header(f"Testing Database: {db_name.upper()}")
        tester = PerformanceTest(db_name)
        
        # Test 1: Connection Performance
        print(f"\n[1/4] Testing connection performance ({num_connections} connections)...")
        for i in range(num_connections):
            duration = tester.test_connection()
            if (i + 1) % 10 == 0:
                print(f"  Completed {i + 1}/{num_connections} connections")
        
        # Test 2: Query Performance
        print(f"\n[2/4] Testing query performance ({num_queries} queries)...")
        for i in range(num_queries):
            duration = tester.test_simple_query()
            if (i + 1) % 20 == 0:
                print(f"  Completed {i + 1}/{num_queries} queries")
        
        # Test 3: Concurrent Load
        print(f"\n[3/4] Testing concurrent load ({concurrent_threads} threads, "
              f"{queries_per_thread} queries each)...")
        concurrent_results = tester.test_concurrent_load(
            concurrent_threads, 
            queries_per_thread
        )
        print(f"  Concurrent test completed in {concurrent_results['duration']:.2f}s")
        print(f"  Throughput: {concurrent_results['queries_per_second']:.1f} queries/sec")
        print(f"  Success rate: {concurrent_results['success_rate']:.1f}%")
        
        # Test 4: Get Pool Metrics
        print(f"\n[4/4] Gathering pool metrics...")
        pool_metrics = get_pool_metrics(db_name)
        
        # Store results
        summary = tester.get_summary()
        summary["concurrent"] = concurrent_results
        summary["pool_metrics"] = pool_metrics.get(db_name, {})
        all_results[db_name] = summary
        
        print("\n✓ Testing complete for", db_name)
        print()
    
    # Print comprehensive report
    print_header("PERFORMANCE REPORT")
    
    for db_name, results in all_results.items():
        print(f"\n{db_name.upper()} DATABASE:")
        print(f"  Connections:")
        print(f"    Total: {results['connections']['total']}")
        print(f"    Success: {results['connections']['successful']}")
        print(f"    Failed: {results['connections']['failed']}")
        print(f"    Avg Time: {results['connections']['avg_time_ms']:.2f}ms")
        print(f"    Min Time: {results['connections']['min_time_ms']:.2f}ms")
        print(f"    Max Time: {results['connections']['max_time_ms']:.2f}ms")
        print(f"    Median Time: {results['connections']['median_time_ms']:.2f}ms")
        
        print(f"\n  Queries:")
        print(f"    Total: {results['queries']['total']}")
        print(f"    Success: {results['queries']['successful']}")
        print(f"    Failed: {results['queries']['failed']}")
        print(f"    Avg Time: {results['queries']['avg_time_ms']:.2f}ms")
        print(f"    Min Time: {results['queries']['min_time_ms']:.2f}ms")
        print(f"    Max Time: {results['queries']['max_time_ms']:.2f}ms")
        print(f"    Median Time: {results['queries']['median_time_ms']:.2f}ms")
        
        print(f"\n  Concurrent Load:")
        print(f"    Duration: {results['concurrent']['duration']:.2f}s")
        print(f"    Total Queries: {results['concurrent']['total_queries']}")
        print(f"    Throughput: {results['concurrent']['queries_per_second']:.1f} queries/sec")
        print(f"    Success Rate: {results['concurrent']['success_rate']:.1f}%")
        
        if results['pool_metrics']:
            pm = results['pool_metrics']
            print(f"\n  Pool Metrics:")
            print(f"    Total Connections: {pm.get('total_connections', 0)}")
            print(f"    Active Connections: {pm.get('active_connections', 0)}")
            print(f"    Failed Connections: {pm.get('failed_connections', 0)}")
            print(f"    Retry Attempts: {pm.get('retry_attempts', 0)}")
            print(f"    Total Queries: {pm.get('total_queries', 0)}")
            print(f"    Success Rate: {pm.get('success_rate', 0):.1f}%")
            print(f"    Avg Connection Time: {pm.get('avg_connection_time_ms', 0):.2f}ms")
        
        if results['errors'] > 0:
            print(f"\n  ⚠ Errors: {results['errors']}")
            if results['error_samples']:
                print(f"    Sample errors:")
                for error in results['error_samples']:
                    print(f"      - {error[:100]}")
    
    # Overall assessment
    print_header("ASSESSMENT")
    
    total_success = sum(r['connections']['successful'] + r['queries']['successful'] 
                       for r in all_results.values())
    total_tests = sum(r['connections']['total'] + r['queries']['total'] 
                     for r in all_results.values())
    overall_success_rate = (total_success / total_tests * 100) if total_tests > 0 else 0
    
    avg_connection_time = statistics.mean([
        r['connections']['avg_time_ms'] 
        for r in all_results.values()
        if r['connections']['avg_time_ms'] > 0
    ])
    
    avg_query_time = statistics.mean([
        r['queries']['avg_time_ms'] 
        for r in all_results.values()
        if r['queries']['avg_time_ms'] > 0
    ])
    
    print(f"\nOverall Success Rate: {overall_success_rate:.1f}%")
    print(f"Average Connection Time: {avg_connection_time:.2f}ms")
    print(f"Average Query Time: {avg_query_time:.2f}ms")
    
    # Performance rating
    if overall_success_rate >= 99 and avg_query_time < 50:
        rating = "EXCELLENT ⭐⭐⭐"
        recommendation = "Database performance is optimal for production."
    elif overall_success_rate >= 95 and avg_query_time < 100:
        rating = "GOOD ⭐⭐"
        recommendation = "Database performance is acceptable for production."
    elif overall_success_rate >= 90 and avg_query_time < 200:
        rating = "FAIR ⭐"
        recommendation = "Consider optimizing connection strings or upgrading tier."
    else:
        rating = "POOR ⚠"
        recommendation = "Database performance issues detected. Review connection settings and tier."
    
    print(f"\nPerformance Rating: {rating}")
    print(f"Recommendation: {recommendation}")
    
    print_separator()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Azure SQL database performance"
    )
    parser.add_argument(
        "--db",
        choices=["core", "send", "inventory", "fulfillment", "all"],
        default="all",
        help="Database to test (default: all)"
    )
    parser.add_argument(
        "--connections",
        type=int,
        default=20,
        help="Number of connection tests (default: 20)"
    )
    parser.add_argument(
        "--queries",
        type=int,
        default=50,
        help="Number of query tests (default: 50)"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=10,
        help="Number of concurrent threads (default: 10)"
    )
    parser.add_argument(
        "--queries-per-thread",
        type=int,
        default=20,
        help="Queries per thread in concurrent test (default: 20)"
    )
    
    args = parser.parse_args()
    
    # Determine which databases to test
    if args.db == "all":
        db_names = ["core", "send", "inventory", "fulfillment"]
    else:
        db_names = [args.db]
    
    try:
        run_database_tests(
            db_names=db_names,
            num_connections=args.connections,
            num_queries=args.queries,
            concurrent_threads=args.threads,
            queries_per_thread=args.queries_per_thread
        )
    except KeyboardInterrupt:
        print("\n\n⚠ Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nCleaning up connection pools...")
        cleanup_all_pools()
        print("✓ Cleanup complete")


if __name__ == "__main__":
    main()