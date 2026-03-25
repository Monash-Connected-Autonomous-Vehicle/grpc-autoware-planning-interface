import threading
from concurrent import futures
from pathlib import Path

import grpc
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped

import planning_pb2
import planning_pb2_grpc
from lanelet_sampling import LaneletMap, yaw_to_quaternion

DEFAULT_INITIAL_X = 3746.734619140625
DEFAULT_INITIAL_Y = 73733.046875

DEFAULT_GOAL_X = 3723.256591796875
DEFAULT_GOAL_Y = 73720.6328125


class PlanningServiceServicer(planning_pb2_grpc.PlanningServiceServicer):
    def __init__(self, ros_node: Node):
        self.node = ros_node
        self.initial_pose_pub = self.node.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10
        )
        self.goal_pub = self.node.create_publisher(
            PoseStamped, "/planning/mission_planning/goal", 10
        )
        map_root = Path(
            self.node.declare_parameter(
                "autoware_map_dir",
                str(Path.home() / "autoware_map"),
            ).value
        )
        map_dir = map_root / "sample-map-planning"
        if not map_dir.exists():
            fallback_dir = Path(__file__).resolve().parent / "sample-map-planning"
            if fallback_dir.exists():
                map_dir = fallback_dir
        osm_path = map_dir / "lanelet2_map.osm"
        self.map = LaneletMap(osm_path)

    def SetInitialPose(self, request, context):
        if request.HasField("x") and request.HasField("y"):
            x, y = request.x, request.y
        else:
            x, y = DEFAULT_INITIAL_X, DEFAULT_INITIAL_Y

        nearest = self.map.nearest_valid_position(x, y)
        if nearest is None:
            message = f"No lanelet point found near x={x}, y={y}"
            self.node.get_logger().warning(message)
            return planning_pb2.PoseReply(success=False, x=0.0, y=0.0, yaw=0.0, message=message)

        pose_msg = PoseWithCovarianceStamped()
        pose_msg.header.stamp = self.node.get_clock().now().to_msg()
        pose_msg.header.frame_id = "map"
        pose_msg.pose.pose.position.x = nearest["x"]
        pose_msg.pose.pose.position.y = nearest["y"]
        pose_msg.pose.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quaternion(nearest["yaw"])
        pose_msg.pose.pose.orientation.x = qx
        pose_msg.pose.pose.orientation.y = qy
        pose_msg.pose.pose.orientation.z = qz
        pose_msg.pose.pose.orientation.w = qw
        pose_msg.pose.covariance = [0.0] * 36
        self.initial_pose_pub.publish(pose_msg)

        return planning_pb2.PoseReply(
            success=True,
            x=nearest["x"],
            y=nearest["y"],
            yaw=nearest["yaw"],
            message="Set initial pose to nearest lanelet centerline point",
        )

    def SetGoalPosition(self, request, context):
        if request.HasField("x") and request.HasField("y"):
            x, y = request.x, request.y
        else:
            x, y = DEFAULT_GOAL_X, DEFAULT_GOAL_Y

        nearest = self.map.nearest_valid_position(x, y)
        if nearest is None:
            message = f"No lanelet point found near x={x}, y={y}"
            self.node.get_logger().warning(message)
            return planning_pb2.PoseReply(success=False, x=0.0, y=0.0, yaw=0.0, message=message)

        pose_msg = PoseStamped()
        pose_msg.header.stamp = self.node.get_clock().now().to_msg()
        pose_msg.header.frame_id = "map"
        pose_msg.pose.position.x = nearest["x"]
        pose_msg.pose.position.y = nearest["y"]
        pose_msg.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quaternion(nearest["yaw"])
        pose_msg.pose.orientation.x = qx
        pose_msg.pose.orientation.y = qy
        pose_msg.pose.orientation.z = qz
        pose_msg.pose.orientation.w = qw
        self.goal_pub.publish(pose_msg)

        return planning_pb2.PoseReply(
            success=True,
            x=nearest["x"],
            y=nearest["y"],
            yaw=nearest["yaw"],
            message="Set goal position to nearest lanelet centerline point",
        )


def start_grpc_server(ros_node: Node, address: str = "0.0.0.0:50051"):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    planning_pb2_grpc.add_PlanningServiceServicer_to_server(
        PlanningServiceServicer(ros_node), server
    )
    server.add_insecure_port(address)
    server.start()
    ros_node.get_logger().info(f"gRPC server listening on {address}")
    server.wait_for_termination()


def main():
    rclpy.init()
    node = Node("planning_grpc_node")

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
