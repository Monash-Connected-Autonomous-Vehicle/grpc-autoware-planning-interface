import math
import threading
from concurrent import futures
from pathlib import Path

import grpc
from grpc_reflection.v1alpha import reflection
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from autoware_vehicle_msgs.msg import Engage
from autoware_planning_msgs.msg import Trajectory

import planning_pb2
import planning_pb2_grpc
from lanelet_sampling import LaneletMap, yaw_to_quaternion

DEFAULT_INITIAL_X = 3746.734619140625
DEFAULT_INITIAL_Y = 73733.046875

DEFAULT_GOAL_X = 3723.256591796875
DEFAULT_GOAL_Y = 73720.6328125

MAP_DOWNLOAD_LINK = (
    "https://drive.google.com/uc?export=download"
    "&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd"
)

BEST_EFFORT_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)


def yaw_to_quaternion(yaw):
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class PlanningServiceServicer(planning_pb2_grpc.PlanningServiceServicer):
    def __init__(self, ros_node: Node):
        self.node = ros_node
        self._lock = threading.Lock()
        self._current_pose = None
        self._current_trajectory = None
        self._engage = False

        self._initial_pose_pub = self.node.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10
        )
        self._goal_pub = self.node.create_publisher(
            PoseStamped, "/planning/mission_planning/goal", 10
        )
        self._engage_pub = self.node.create_publisher(
            Engage, "/autoware/engage", 10
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

        ros_node.create_subscription(
            Odometry,
            "/localization/kinematic_state",
            self._on_kinematic_state,
            BEST_EFFORT_QOS,
        )
        ros_node.create_subscription(
            Trajectory,
            "/planning/scenario_planning/trajectory",
            self._on_trajectory,
            BEST_EFFORT_QOS,
        )

    def _on_kinematic_state(self, msg: Odometry):
        pos = msg.pose.pose.position
        yaw = quaternion_to_yaw(msg.pose.pose.orientation)
        with self._lock:
            self._current_pose = (pos.x, pos.y, yaw)

    def _on_trajectory(self, msg: Trajectory):
        points = [(p.pose.position.x, p.pose.position.y) for p in msg.points]
        with self._lock:
            self._current_trajectory = points

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
        self._initial_pose_pub.publish(pose_msg)

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
        self._goal_pub.publish(pose_msg)

        return planning_pb2.PoseReply(
            success=True,
            x=nearest["x"],
            y=nearest["y"],
            yaw=nearest["yaw"],
            message="Set goal position to nearest lanelet centerline point",
        )

    def GetMapDownloadLink(self, request, context):
        self.node.get_logger().info("GetMapDownloadLink")
        return planning_pb2.GetMapDownloadLinkResponse(
            osm_link=MAP_DOWNLOAD_LINK,
            pcd_link=MAP_DOWNLOAD_LINK,
        )

    def GoToDestination(self, request, context):
        self.node.get_logger().info("GoToDestination: engaging")
        self._engage = True
        engage_msg = Engage()
        engage_msg.engage = True
        self._engage_pub.publish(engage_msg)
        return planning_pb2.GoToDestinationResponse(
            success=True, message="Engaged autonomous driving"
        )

    def GetPathToDestination(self, request, context):
        with self._lock:
            trajectory = self._current_trajectory
        self.node.get_logger().info(
            f"GetPathToDestination: {len(trajectory) if trajectory else 0} points"
        )
        resp = planning_pb2.GetPathResponse()
        if trajectory:
            for x, y in trajectory:
                resp.path.append(planning_pb2.Position(x=x, y=y))
        return resp

    def GetCurrentPose(self, request, context):
        with self._lock:
            pose = self._current_pose
        if pose:
            x, y, direction = pose
            return planning_pb2.GetCurrentPoseResponse(x=x, y=y, direction=direction)
        return planning_pb2.GetCurrentPoseResponse(x=0.0, y=0.0, direction=0.0)

def quaternion_to_yaw(orientation):
    x, y, z, w = orientation.x, orientation.y, orientation.z, orientation.w
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def main():
    rclpy.init()
    node = Node("planning_grpc_node")

    servicer = PlanningServiceServicer(node)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    planning_pb2_grpc.add_PlanningServiceServicer_to_server(
        servicer, server
    )
    SERVICE_NAMES = (
        planning_pb2.DESCRIPTOR.services_by_name['PlanningService'].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    node.get_logger().info("gRPC server listening on 0.0.0.0:50051")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down")
    finally:
        server.stop(grace=2)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
