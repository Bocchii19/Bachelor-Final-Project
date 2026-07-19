// Backend host — dùng IP cố định của Jetson
const BACKEND_HOST = '10.128.55.227'
const BACKEND_PORT = 9000

export const apiConfig = {
  baseUrl: `http://${BACKEND_HOST}:${BACKEND_PORT}/api`,
  wsUrl: `ws://${BACKEND_HOST}:${BACKEND_PORT}/ws`,
}
