module exp_fixed_point #(
  parameter WIDTH = 8
) (
  input  logic               clk,
  input  logic               rst,
  input  logic               enable,
  input  logic [WIDTH-1:0]   x_in,
  output logic [2*WIDTH-1:0] exp_out
);

  localparam integer FRAC_BITS = WIDTH - 1;
  localparam integer OUT_W     = 2 * WIDTH;
  localparam integer ACC_W     = 4 * WIDTH;

  logic [ACC_W-1:0] x_ext;
  logic [ACC_W-1:0] x_sq;
  logic [ACC_W-1:0] x_cu;
  logic [ACC_W-1:0] term_1;
  logic [ACC_W-1:0] term_x;
  logic [ACC_W-1:0] term_x2;
  logic [ACC_W-1:0] term_x3;
  logic [ACC_W-1:0] exp_sum;
  logic [OUT_W-1:0] exp_next;

  always_comb begin
    x_ext  = {{(ACC_W-WIDTH){1'b0}}, x_in};
    x_sq   = x_ext * x_ext;
    x_cu   = x_sq * x_ext;

    term_1 = {ACC_W{1'b0}};
    term_x = {ACC_W{1'b0}};
    term_1[FRAC_BITS] = 1'b1;
    term_x[WIDTH-1:0] = x_in;

    term_x2 = x_sq >> WIDTH;
    term_x3 = (x_cu >> (2 * FRAC_BITS)) / 6;
    exp_sum = term_1 + term_x + term_x2 + term_x3;

    if (|exp_sum[ACC_W-1:OUT_W]) begin
      exp_next = {OUT_W{1'b1}};
    end else begin
      exp_next = exp_sum[OUT_W-1:0];
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      exp_out <= {OUT_W{1'b0}};
    end else if (enable) begin
      exp_out <= exp_next;
    end
  end

endmodule
