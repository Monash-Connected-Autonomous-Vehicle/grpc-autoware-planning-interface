import threading
from concurrent import futures

import grpc
import rclpy
from rclpy.node import Node

import example_pb2
import example_pb2_grpc


class ExampleServiceServicer(example_pb2_grpc.ExampleServiceServicer):
    def __init__(self, ros_node: Node):
        self.node = ros_node

    def Ping(self, request, context):
        self.node.get_logger().info(f"Received Ping: {request.message}")
        # No-op logic; just echo back
        return example_pb2.PingReply(message=f"Echo: {request.message}")


def start_grpc_server(ros_node: Node, address: str = "0.0.0.0:50051"):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    example_pb2_grpc.add_ExampleServiceServicer_to_server(
        ExampleServiceServicer(ros_node), server
    )
    server.add_insecure_port(address)
    server.start()
    ros_node.get_logger().info(f"gRPC server listening on {address}")
    server.wait_for_termination()


def main():
    rclpy.init()
    node = Node("example_grpc_node")

    # Run gRPC server in a background thread so rclpy can spin
    grpc_thread = threading.Thread(
        target=start_grpc_server, args=(node,), daemon=True
    )
    grpc_thread.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
