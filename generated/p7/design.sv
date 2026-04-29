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

  logic [WIDTH-1:0]      x_s0;
  logic [2*WIDTH-1:0]    x2_s1;
  logic [3*WIDTH-1:0]    x3_s1;

  logic [2*WIDTH-1:0]    one_term_c;
  logic [2*WIDTH-1:0]    x_term_c;
  logic [2*WIDTH-1:0]    x2_scaled_c;
  logic [2*WIDTH-1:0]    x3_scaled_c;
  logic [2*WIDTH-1:0]    x2_div2_c;
  logic [2*WIDTH-1:0]    x3_div6_c;
  logic [2*WIDTH-1:0]    sum1_c;
  logic [2*WIDTH-1:0]    sum2_c;
  logic [2*WIDTH-1:0]    exp_next_c;

  always @(*) begin
    one_term_c  = {((2*WIDTH)){1'b0}};
    x_term_c    = {((2*WIDTH)){1'b0}};
    x2_scaled_c = {((2*WIDTH)){1'b0}};
    x3_scaled_c = {((2*WIDTH)){1'b0}};
    x2_div2_c   = {((2*WIDTH)){1'b0}};
    x3_div6_c   = {((2*WIDTH)){1'b0}};
    sum1_c      = {((2*WIDTH)){1'b0}};
    sum2_c      = {((2*WIDTH)){1'b0}};
    exp_next_c  = {((2*WIDTH)){1'b0}};

    one_term_c[FRAC_BITS] = 1'b1;
    x_term_c = {{WIDTH{1'b0}}, x_s0};

    x2_scaled_c = x2_s1 >> FRAC_BITS;
    x3_scaled_c = x3_s1 >> (2*FRAC_BITS);

    x2_div2_c = x2_scaled_c >> 1;
    x3_div6_c = x3_scaled_c / 6;

    sum1_c = one_term_c + x_term_c;
    sum2_c = sum1_c + x2_div2_c;
    exp_next_c = sum2_c + x3_div6_c;
  end

  always @(posedge clk) begin
    if (rst) begin
      x_s0    <= {WIDTH{1'b0}};
      x2_s1   <= {(2*WIDTH){1'b0}};
      x3_s1   <= {(3*WIDTH){1'b0}};
      exp_out <= {(2*WIDTH){1'b0}};
    end else if (enable) begin
      x_s0    <= x_in;
      x2_s1   <= x_in * x_in;
      x3_s1   <= (x_in * x_in) * x_in;
      exp_out <= exp_next_c;
    end
  end

endmodule
