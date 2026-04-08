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

    localparam int ACC_WIDTH = 2*WIDTH + 4;

    logic signed [ACC_WIDTH-1:0] dot_comb;
    integer i;

    always_comb begin
        dot_comb = '0;
        for (i = 0; i < N; i = i + 1) begin
            dot_comb = dot_comb + ($signed(A[i]) * $signed(B[i]));
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            dot_out <= '0;
            valid   <= 1'b0;
        end else begin
            dot_out <= dot_comb;
            valid   <= 1'b1;
        end
    end

endmodule
