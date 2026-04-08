module dot_product #(
    parameter int N = 8,
    parameter int WIDTH = 8
) (
    input  logic clk,
    input  logic rst,
    input  logic signed [N-1:0][WIDTH-1:0] A,
    input  logic signed [N-1:0][WIDTH-1:0] B,
    output logic signed [2*WIDTH+3:0] dot_out,
    output logic valid
);

    localparam int PROD_WIDTH = 2*WIDTH;
    localparam int ACC_WIDTH  = 2*WIDTH + 4;

    logic signed [N-1:0][PROD_WIDTH-1:0] product_reg;
    logic signed [ACC_WIDTH-1:0] accum_comb;
    logic [1:0] valid_pipe;

    integer i;
    logic signed [ACC_WIDTH-1:0] prod_ext;

    always_comb begin
        accum_comb = '0;
        for (i = 0; i < N; i = i + 1) begin
            prod_ext = {{(ACC_WIDTH-PROD_WIDTH){product_reg[i][PROD_WIDTH-1]}}, product_reg[i]};
            accum_comb = accum_comb + prod_ext;
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N; i = i + 1) begin
                product_reg[i] <= '0;
            end
            dot_out    <= '0;
            valid_pipe <= 2'b00;
            valid      <= 1'b0;
        end else begin
            for (i = 0; i < N; i = i + 1) begin
                product_reg[i] <= $signed(A[i]) * $signed(B[i]);
            end
            dot_out    <= accum_comb;
            valid_pipe <= {valid_pipe[0], 1'b1};
            valid      <= valid_pipe[1];
        end
    end

endmodule
