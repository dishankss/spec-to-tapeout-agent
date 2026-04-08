module fir_filter #(
  parameter WIDTH = 16,
  parameter N = 8
) (
  input  logic                              clk,
  input  logic                              rst,
  input  logic signed [WIDTH-1:0]           x_in,
  input  logic signed [N-1:0][WIDTH-1:0]    h,
  output logic signed [2*WIDTH+$clog2(N):0] y_out
);

  localparam int PROD_W = 2 * WIDTH;
  localparam int ACC_W  = 2 * WIDTH + $clog2(N) + 1;
  localparam int STAGES = (N > 1) ? $clog2(N) : 1;

  logic signed [WIDTH-1:0] sample_pipe [0:N-1];
  logic signed [PROD_W-1:0] prod_pipe [0:N-1];
  logic signed [ACC_W-1:0]  sum_pipe  [0:STAGES-1][0:N-1];

  function automatic logic signed [ACC_W-1:0] extend_prod(
    input logic signed [PROD_W-1:0] value
  );
    extend_prod = {{(ACC_W-PROD_W){value[PROD_W-1]}}, value};
  endfunction

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

  always_ff @(posedge clk) begin
    if (rst) begin
      for (i = 0; i < N; i = i + 1) begin
        prod_pipe[i] <= '0;
      end
    end else begin
      for (i = 0; i < N; i = i + 1) begin
        prod_pipe[i] <= sample_pipe[i] * h[i];
      end
    end
  end

  genvar s;
  generate
    for (s = 0; s < STAGES; s = s + 1) begin : gen_adder_tree
      integer k;
      if (s == 0) begin : gen_first_stage
        always_ff @(posedge clk) begin
          if (rst) begin
            for (k = 0; k < N; k = k + 1) begin
              sum_pipe[s][k] <= '0;
            end
          end else begin
            for (k = 0; k < N; k = k + 1) begin
              if ((2*k + 1) < N) begin
                sum_pipe[s][k] <= extend_prod(prod_pipe[2*k]) + extend_prod(prod_pipe[2*k+1]);
              end else if ((2*k) < N) begin
                sum_pipe[s][k] <= extend_prod(prod_pipe[2*k]);
              end else begin
                sum_pipe[s][k] <= '0;
              end
            end
          end
        end
      end else begin : gen_later_stage
        always_ff @(posedge clk) begin
          if (rst) begin
            for (k = 0; k < N; k = k + 1) begin
              sum_pipe[s][k] <= '0;
            end
          end else begin
            for (k = 0; k < N; k = k + 1) begin
              if ((2*k + 1) < N) begin
                sum_pipe[s][k] <= sum_pipe[s-1][2*k] + sum_pipe[s-1][2*k+1];
              end else if ((2*k) < N) begin
                sum_pipe[s][k] <= sum_pipe[s-1][2*k];
              end else begin
                sum_pipe[s][k] <= '0;
              end
            end
          end
        end
      end
    end
  endgenerate

  always_comb begin
    y_out = sum_pipe[STAGES-1][0];
  end

endmodule
