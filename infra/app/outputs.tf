# Written into ui/.env.local and the simulator config at deploy time, never
# printed into proof files.

output "ws_url" {
  value     = "${aws_apigatewayv2_api.ws.api_endpoint}/${aws_apigatewayv2_stage.demo.name}"
  sensitive = true
}

output "connect_token" {
  value     = random_password.connect_token.result
  sensitive = true
}

output "event_bus" {
  value = aws_cloudwatch_event_bus.main.name
}

output "esm_uuids" {
  value = { for k, v in aws_lambda_event_source_mapping.positions : k => v.uuid }
}
