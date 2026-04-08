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
  localparam integer X2_W      = 2 * WIDTH;
  localparam integer X3_W      = 3 * WIDTH;
  localparam integer SUM_W     = OUT_W + 2;

  logic               valid_s1;
  logic               valid_s2;
  logic [WIDTH-1:0]   x_s1;
  logic [X2_W-1:0]    x2_s1;
  logic [X3_W-1:0]    x3_s1;
  logic [OUT_W-1:0]   sum_s2;

  logic [OUT_W-1:0]   one_term_c;
  logic [OUT_W-1:0]   x_term_c;
  logic [OUT_W-1:0]   x2_term_c;
  logic [OUT_W-1:0]   x3_term_c;
  logic [SUM_W-1:0]   sum_c;
  logic [X3_W-1:0]    x3_scaled_c;
  logic [X3_W-1:0]    x3_div6_c;

  assign one_term_c  = {{WIDTH{1'b0}}, 1'b1, {FRAC_BITS{1'b0}}};
  assign x_term_c    = {{WIDTH{1'b0}}, x_s1};
  assign x2_term_c   = x2_s1 >> (FRAC_BITS + 1);
  assign x3_scaled_c = x3_s1 >> (2 * FRAC_BITS);
  assign x3_div6_c   = x3_scaled_c / X3_W'(6);
  assign x3_term_c   = x3_div6_c[OUT_W-1:0];

  assign sum_c = {{2{1'b0}}, one_term_c}
               + {{2{1'b0}}, x_term_c}
               + {{2{1'b0}}, x2_term_c}
               + {{2{1'b0}}, x3_term_c};

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_s1 <= 1'b0;
      valid_s2 <= 1'b0;
      x_s1     <= {WIDTH{1'b0}};
      x2_s1    <= {X2_W{1'b0}};
      x3_s1    <= {X3_W{1'b0}};
      sum_s2   <= {OUT_W{1'b0}};
      exp_out  <= {OUT_W{1'b0}};
    end else begin
      valid_s1 <= enable;
      valid_s2 <= valid_s1;

      if (enable) begin
        x_s1  <= x_in;
        x2_s1 <= x_in * x_in;
        x3_s1 <= (x_in * x_in) * x_in;
      end

      if (valid_s1) begin
        sum_s2 <= sum_c[OUT_W-1:0];
      end else begin
        sum_s2 <= {OUT_W{1'b0}};
      end

      if (valid_s2) begin
        exp_out <= sum_s2;
      end else begin
        exp_out <= {OUT_W{1'b0}};
      end
    end
  end

endmodule
