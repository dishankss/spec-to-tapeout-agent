module exp_fixed_point #(
  parameter WIDTH = 8
) (
  input  logic               clk,
  input  logic               rst,
  input  logic               enable,
  input  logic [WIDTH-1:0]   x_in,
  output logic [2*WIDTH-1:0] exp_out
);

  localparam int OUT_W   = 2 * WIDTH;
  localparam int X2_W    = 2 * WIDTH;
  localparam int X3_W    = 3 * WIDTH;
  localparam int X2_SHIFT = WIDTH;
  localparam int X3_SHIFT = (2 * WIDTH) - 2;

  logic [WIDTH-1:0]   x_s1;
  logic [X2_W-1:0]    x2_s1;
  logic [X3_W-1:0]    x3_s1;

  logic [OUT_W-1:0]   term_one_s2;
  logic [OUT_W-1:0]   term_x_s2;
  logic [OUT_W-1:0]   term_x2_s2;
  logic [OUT_W-1:0]   term_x3_s2;
  logic [OUT_W-1:0]   sum_s2;

  logic [OUT_W-1:0]   x_ext_s1;
  logic [OUT_W-1:0]   x2_scaled_s1;
  logic [OUT_W-1:0]   x3_base_s1;
  logic [OUT_W-1:0]   x3_div6_s1;

  assign x_ext_s1    = {{WIDTH{1'b0}}, x_s1};
  assign term_one_s2 = {{(OUT_W-1){1'b0}}, 1'b1} << (WIDTH-1);
  assign term_x_s2   = x_ext_s1;
  assign x2_scaled_s1 = x2_s1 >> X2_SHIFT;
  assign term_x2_s2   = x2_scaled_s1;
  assign x3_base_s1   = x3_s1 >> X3_SHIFT;
  assign x3_div6_s1   = x3_base_s1 / OUT_W'(6);
  assign term_x3_s2   = x3_div6_s1;

  assign sum_s2 = term_one_s2 + term_x_s2 + term_x2_s2 + term_x3_s2;

  always_ff @(posedge clk) begin
    if (rst) begin
      x_s1    <= '0;
      x2_s1   <= '0;
      x3_s1   <= '0;
      exp_out <= '0;
    end else if (enable) begin
      x_s1    <= x_in;
      x2_s1   <= x_in * x_in;
      x3_s1   <= (x_in * x_in) * x_in;
      exp_out <= sum_s2;
    end
  end

endmodule
