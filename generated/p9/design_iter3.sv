module fir_filter #(
  parameter WIDTH = 16,
  parameter N = 8
) (
  input  logic                             clk,
  input  logic                             rst,
  input  logic signed [WIDTH-1:0]          x_in,
  input  logic signed [N-1:0][WIDTH-1:0]   h,
  output logic signed [2*WIDTH+$clog2(N):0] y_out
);

  localparam int ACC_W  = 2*WIDTH + $clog2(N) + 1;
  localparam int PROD_W = 2*WIDTH;

  logic signed [WIDTH-1:0] sample_pipe [0:N-1];
  logic signed [ACC_W-1:0] acc_sum;
  logic signed [PROD_W-1:0] product;
  integer i;

  always_ff @(posedge clk) begin
    if (rst) begin
      for (i = 0; i < N; i = i + 1) begin
        sample_pipe[i] <= '0;
      end
    end else begin
      sample_pipe[0] <= x_in;
      for (i = 1; i < N; i = i + 1) begin
        sample_pipe[i] <= sample_pipe[i-1];
      end
    end
  end

  always_comb begin
    acc_sum = '0;
    for (i = 0; i < N; i = i + 1) begin
      product = sample_pipe[i] * h[i];
      acc_sum = acc_sum + {{(ACC_W-PROD_W){product[PROD_W-1]}}, product};
    end

    if (rst) begin
      y_out = '0;
    end else begin
      y_out = acc_sum;
    end
  end

endmodule
