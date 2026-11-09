using UnityEngine;
using UnityEngine.InputSystem;

namespace RoomAR
{
    /// <summary>
    /// WASD + 마우스 플라이 카메라 (새 Input System).
    /// 마우스 오른쪽 버튼을 누른 동안 시점 회전, Q/E 하강/상승, Shift 가속.
    /// 왼쪽 클릭은 SandboxController가 힘 가하기에 사용하므로 비워 둡니다.
    /// </summary>
    public class FlyCamera : MonoBehaviour
    {
        [SerializeField] float moveSpeed = 1.5f;      // m/s (방이 작으므로 느리게)
        [SerializeField] float fastMultiplier = 3f;
        [SerializeField] float lookSensitivity = 0.12f; // deg per pixel

        float yaw;
        float pitch;

        void OnEnable()
        {
            var e = transform.eulerAngles;
            yaw = e.y;
            pitch = e.x > 180f ? e.x - 360f : e.x;
        }

        void Update()
        {
            var kb = Keyboard.current;
            var mouse = Mouse.current;
            if (kb == null || mouse == null) return;

            // 시점 회전
            if (mouse.rightButton.isPressed)
            {
                Vector2 d = mouse.delta.ReadValue();
                yaw += d.x * lookSensitivity;
                pitch = Mathf.Clamp(pitch - d.y * lookSensitivity, -89f, 89f);
                transform.rotation = Quaternion.Euler(pitch, yaw, 0f);
            }

            // 이동
            Vector3 move = Vector3.zero;
            if (kb.wKey.isPressed) move += Vector3.forward;
            if (kb.sKey.isPressed) move += Vector3.back;
            if (kb.dKey.isPressed) move += Vector3.right;
            if (kb.aKey.isPressed) move += Vector3.left;
            Vector3 world = transform.TransformDirection(move);
            if (kb.eKey.isPressed) world += Vector3.up;
            if (kb.qKey.isPressed) world += Vector3.down;

            if (world.sqrMagnitude > 0f)
            {
                float speed = moveSpeed * (kb.leftShiftKey.isPressed ? fastMultiplier : 1f);
                transform.position += world.normalized * speed * Time.unscaledDeltaTime;
            }
        }
    }
}
