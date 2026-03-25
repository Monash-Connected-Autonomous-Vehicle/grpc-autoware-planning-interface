import math
import threading
from concurrent import futures

import grpc
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from autoware_vehicle_msgs.msg import Engage
from autoware_planning_msgs.msg import Trajectory

import planning_pb2
import planning_pb2_grpc

MAP_DOWNLOAD_LINK = (
    "https://drive.google.com/uc?export=download"
    "&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd"
)

BEST_EFFORT_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)


def quaternion_to_yaw(orientation):
    x, y, z, w = orientation.x, orientation.y, orientation.z, orientation.w
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def yaw_to_quaternion(yaw):
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class AutowarePlanningServicer(planning_pb2_grpc.AutowarePlanningServiceServicer):
    def __init__(self, ros_node: Node):
        self.node = ros_node
        self._lock = threading.Lock()
        self._destination = None
        self._current_pose = None
        self._current_trajectory = None

        self._goal_pub = ros_node.create_publisher(
            PoseStamped, "/planning/mission_planning/goal", 10
        )
        self._engage_pub = ros_node.create_publisher(
            Engage, "/autoware/engage", 10
        )
        self._initialpose_pub = ros_node.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10
        )

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

    def _publish_goal(self, x: float, y: float):
        msg = PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.node.get_clock().now().to_msg()
        msg.pose.position.x = x
        msg.pose.position.y = y
        msg.pose.position.z = 0.0
        msg.pose.orientation.w = 1.0
        self._goal_pub.publish(msg)

    def _publish_engage(self, engage: bool):
        msg = Engage()
        msg.engage = engage
        self._engage_pub.publish(msg)

    def SetDestination(self, request, context):
        x, y = request.position.x, request.position.y
        self.node.get_logger().info(f"SetDestination: x={x}, y={y}")

        with self._lock:
            self._destination = (x, y)

        self._publish_goal(x, y)

        return planning_pb2.SetDestinationResponse(
            success=True, message=f"Destination set to ({x}, {y})"
        )

    def GoToDestination(self, request, context):
        if request.HasField("position"):
            x, y = request.position.x, request.position.y
            self.node.get_logger().info(f"GoToDestination: override to x={x}, y={y}")
            with self._lock:
                self._destination = (x, y)
            self._publish_goal(x, y)
        else:
            with self._lock:
                dest = self._destination
            if dest is None:
                self.node.get_logger().warn("GoToDestination: no destination set")
                return planning_pb2.GoToDestinationResponse(
                    success=False, message="No destination set. Call SetDestination first."
                )
            self.node.get_logger().info(
                f"GoToDestination: engaging to ({dest[0]}, {dest[1]})"
            )

        self._publish_engage(True)

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
            self.node.get_logger().info(
                f"GetCurrentPose: x={x:.2f}, y={y:.2f}, yaw={direction:.2f}"
            )
            return planning_pb2.GetCurrentPoseResponse(
                pose=planning_pb2.Pose(x=x, y=y, direction=direction)
            )

        self.node.get_logger().info("GetCurrentPose: no pose received yet")
        return planning_pb2.GetCurrentPoseResponse(
            pose=planning_pb2.Pose(x=0.0, y=0.0, direction=0.0)
        )

    def GetMapDownloadLink(self, request, context):
        self.node.get_logger().info("GetMapDownloadLink")
        return planning_pb2.GetMapDownloadLinkResponse(
            osm_link=MAP_DOWNLOAD_LINK,
            pcd_link=MAP_DOWNLOAD_LINK,
        )

    def Reset(self, request, context):
        if request.HasField("position"):
            x, y = request.position.x, request.position.y
        else:
            x, y = 0.0, 0.0

        self.node.get_logger().info(f"Reset: initial pose to x={x}, y={y}")

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.node.get_clock().now().to_msg()
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.w = 1.0
        msg.pose.covariance = [0.0] * 36

        self._initialpose_pub.publish(msg)
        self._publish_engage(False)

        with self._lock:
            self._destination = None

        return planning_pb2.ResetResponse(
            success=True, message=f"Reset to ({x}, {y})"
        )


def main():
    rclpy.init()
    node = Node("autoware_planning_grpc_node")

    servicer = AutowarePlanningServicer(node)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    planning_pb2_grpc.add_AutowarePlanningServiceServicer_to_server(
        servicer, server
    )
    server.add_insecure_port("0.0.0.0:50052")
    server.start()
    node.get_logger().info("gRPC server listening on 0.0.0.0:50052")

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
