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

  localparam integer PROD_W      = 2 * WIDTH;
  localparam integer OUT_W       = 2 * WIDTH + $clog2(N) + 1;
  localparam integer PIPE_STAGES = (N > 1) ? (N - 1) : 1;

  logic signed [OUT_W-1:0]  pipe_reg [0:PIPE_STAGES-1];
  logic signed [PROD_W-1:0] mult_val [0:N-1];
  logic signed [OUT_W-1:0]  mult_ext [0:N-1];

  genvar gi;
  generate
    for (gi = 0; gi < N; gi = gi + 1) begin : gen_mult
      assign mult_val[gi] = x_in * h[gi];
      assign mult_ext[gi] = {{(OUT_W - PROD_W){mult_val[gi][PROD_W-1]}}, mult_val[gi]};
    end
  endgenerate

  generate
    if (N == 1) begin : gen_n_eq_1
      always @(posedge clk) begin
        if (rst) begin
          y_out <= '0;
          pipe_reg[0] <= '0;
        end else begin
          y_out <= mult_ext[0];
          pipe_reg[0] <= '0;
        end
      end
    end else begin : gen_n_gt_1
      integer i;
      always @(posedge clk) begin
        if (rst) begin
          y_out <= '0;
          for (i = 0; i < PIPE_STAGES; i = i + 1) begin
            pipe_reg[i] <= '0;
          end
        end else begin
          y_out <= mult_ext[0] + pipe_reg[0];
          for (i = 0; i < N - 2; i = i + 1) begin
            pipe_reg[i] <= mult_ext[i+1] + pipe_reg[i+1];
          end
          pipe_reg[N-2] <= mult_ext[N-1];
        end
      end
    end
  endgenerate

endmodule
